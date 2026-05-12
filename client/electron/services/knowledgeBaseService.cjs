const crypto = require('node:crypto');
const fs = require('node:fs');
const fsp = require('node:fs/promises');
const path = require('node:path');
const { dialog } = require('electron');
const { getKnowledgeBaseDir } = require('../utils/paths.cjs');

const supportedExtensions = new Set(['.doc', '.docx', '.wps', '.pdf', '.md', '.markdown']);
const targetChunkChars = 60000;
const maxChunkChars = 100000;
const minChunkChars = 8000;

function now() {
  return new Date().toISOString();
}

function createId(prefix) {
  return `${prefix}-${crypto.randomUUID()}`;
}

function safeName(name) {
  return String(name || '未命名').replace(/[<>:"/\\|?*\x00-\x1F]+/g, '_').trim() || '未命名';
}

function createEmptyIndex() {
  return { folders: [], documents: [] };
}

function normalizeIndex(index) {
  return {
    folders: Array.isArray(index?.folders) ? index.folders : [],
    documents: Array.isArray(index?.documents) ? index.documents : [],
  };
}

function ensureDir(dir) {
  fs.mkdirSync(dir, { recursive: true });
}

function readJson(filePath, fallback) {
  if (!fs.existsSync(filePath)) {
    return fallback;
  }
  return JSON.parse(fs.readFileSync(filePath, 'utf-8'));
}

function writeJson(filePath, value) {
  ensureDir(path.dirname(filePath));
  fs.writeFileSync(filePath, JSON.stringify(value, null, 2), 'utf-8');
}

function getIndexPath(baseDir) {
  return path.join(baseDir, 'index.json');
}

function toRelative(baseDir, filePath) {
  return path.relative(baseDir, filePath).replace(/\\/g, '/');
}

function fromRelative(baseDir, relativePath) {
  return path.join(baseDir, relativePath || '');
}

function stripMarkdownFence(content) {
  return String(content || '').replace(/^```[\s\S]*?\n/, '').replace(/```$/g, '').trim();
}

function splitOversizedText(text, limit) {
  const parts = [];
  let buffer = '';
  const sentences = String(text || '').split(/(?<=[。！？!?；;])\s*/);
  for (const sentence of sentences) {
    if (!sentence) continue;
    if (buffer && buffer.length + sentence.length > limit) {
      parts.push(buffer.trim());
      buffer = '';
    }
    buffer += sentence;
  }
  if (buffer.trim()) {
    parts.push(buffer.trim());
  }
  return parts.length ? parts : [String(text || '')];
}

function createMarkdownBlocks(markdown) {
  const blocks = [];
  const lines = String(markdown || '').split(/\r?\n/);
  let buffer = [];
  let currentType = 'paragraph';
  const headings = [];

  function pushBuffer() {
    const content = buffer.join('\n').trim();
    if (!content) {
      buffer = [];
      return;
    }

    const chunks = content.length > maxChunkChars ? splitOversizedText(content, targetChunkChars) : [content];
    for (const chunk of chunks) {
      const id = `B${String(blocks.length + 1).padStart(5, '0')}`;
      blocks.push({ id, type: currentType, heading_path: [...headings], content: chunk });
    }
    buffer = [];
  }

  for (const line of lines) {
    const headingMatch = /^(#{1,6})\s+(.+)$/.exec(line);
    if (headingMatch) {
      pushBuffer();
      const level = headingMatch[1].length;
      headings.splice(level - 1);
      headings[level - 1] = headingMatch[2].trim();
      currentType = 'heading';
      buffer = [line];
      pushBuffer();
      currentType = 'paragraph';
      continue;
    }

    const isTableLine = /^\s*\|.*\|\s*$/.test(line);
    const nextType = isTableLine ? 'table' : 'paragraph';
    if (buffer.length && currentType !== nextType && (currentType === 'table' || nextType === 'table')) {
      pushBuffer();
    }
    currentType = nextType;

    if (!line.trim()) {
      pushBuffer();
      currentType = 'paragraph';
      continue;
    }

    buffer.push(line);
  }
  pushBuffer();
  return blocks;
}

function renderAnnotatedBlocks(blocks) {
  return blocks.map((block) => {
    const pathLabel = block.heading_path.filter(Boolean).join(' > ');
    return `[${block.id}]${pathLabel ? ` (${pathLabel})` : ''}\n${block.content}`;
  }).join('\n\n');
}

function createChunks(blocks) {
  const chunks = [];
  let current = [];
  let size = 0;

  function pushCurrent() {
    if (!current.length) return;
    chunks.push(current);
    current = [];
    size = 0;
  }

  for (const block of blocks) {
    const blockSize = block.content.length;
    if (current.length && size >= minChunkChars && size + blockSize > targetChunkChars) {
      pushCurrent();
    }
    current.push(block);
    size += blockSize;
    if (size >= maxChunkChars) {
      pushCurrent();
    }
  }
  pushCurrent();
  return chunks;
}

function normalizeDecisionItems(parsed) {
  const items = Array.isArray(parsed) ? parsed : parsed?.items;
  if (!Array.isArray(items)) return [];
  return items.map((item) => ({
    title: String(item?.title || '').trim(),
    resume: String(item?.resume || item?.summary || '').trim(),
    source_block_ids: Array.isArray(item?.source_block_ids) ? item.source_block_ids.map(String) : [],
  })).filter((item) => item.title && item.resume && item.source_block_ids.length);
}

function validateDecisionItems(value) {
  const items = Array.isArray(value) ? value : value?.items;
  if (!Array.isArray(items)) {
    throw new Error('AI 返回结果缺少 items 数组');
  }
}

function buildDecisionMessages(documentName, chunkIndex, chunkCount, annotatedMarkdown) {
  return [
    {
      role: 'system',
      content: '你是投标资料知识库整理助手。你只负责判断哪些原文片段值得沉淀为可复用知识条目，不要改写原文，不要输出完整原文。必须输出 JSON 对象。',
    },
    {
      role: 'user',
      content: [
        `文档名：${documentName}`,
        `当前片段：${chunkIndex + 1}/${chunkCount}`,
        '请从下面带有块编号的 Markdown 中整理知识条目。',
        '输出格式：{"items":[{"title":"","resume":"","source_block_ids":["B00001"]}]}',
        '要求：title 简洁明确；resume 说明该资料可如何复用；source_block_ids 必须只引用输入中存在的块编号；相邻连续块可以同时引用；不要输出 content 字段。',
        '',
        annotatedMarkdown,
      ].join('\n'),
    },
  ];
}

function normalizeBlockIds(ids, blockMap) {
  return [...new Set(ids.map(String).filter((id) => blockMap.has(id)))];
}

function buildKnowledgeItems(decisions, blockMap, fileName) {
  const merged = new Map();
  for (const decision of decisions) {
    const blockIds = normalizeBlockIds(decision.source_block_ids, blockMap);
    if (!blockIds.length) continue;
    const key = `${decision.title}\n${decision.resume}`;
    const prev = merged.get(key) || { title: decision.title, resume: decision.resume, source_block_ids: [] };
    prev.source_block_ids = [...new Set([...prev.source_block_ids, ...blockIds])];
    merged.set(key, prev);
  }

  return Array.from(merged.values()).map((item) => {
    const content = item.source_block_ids.map((id) => blockMap.get(id)?.content || '').filter(Boolean).join('\n\n').trim();
    const hash = crypto.createHash('sha1').update(`${fileName}\n${item.title}\n${item.source_block_ids.join(',')}`).digest('hex').slice(0, 16);
    return { id: `kb-${hash}`, title: item.title, resume: item.resume, content, source_block_ids: item.source_block_ids, source_file: fileName };
  }).filter((item) => item.content);
}

function createKnowledgeBaseService({ app, aiService }) {
  const baseDir = getKnowledgeBaseDir(app);
  const indexPath = getIndexPath(baseDir);

  function loadIndex() {
    ensureDir(baseDir);
    return normalizeIndex(readJson(indexPath, createEmptyIndex()));
  }

  function saveIndex(index) {
    writeJson(indexPath, normalizeIndex(index));
    return normalizeIndex(index);
  }

  function emitProgress(webContents, document) {
    if (!webContents?.isDestroyed()) {
      webContents.send('knowledge-base:event', { document });
    }
  }

  function updateDocument(documentId, partial, webContents) {
    const index = loadIndex();
    const documents = index.documents.map((document) => (
      document.id === documentId ? { ...document, ...partial, updated_at: now() } : document
    ));
    const next = saveIndex({ ...index, documents });
    const document = next.documents.find((item) => item.id === documentId);
    if (document) emitProgress(webContents, document);
    return document;
  }

  async function processDocument(documentId, sourceFilePath, webContents) {
    const { convertPathToMarkdown } = await import('./doc2markdown/convert.mjs');
    const index = loadIndex();
    const document = index.documents.find((item) => item.id === documentId);
    if (!document) throw new Error('知识库文档不存在');

    const documentDir = fromRelative(baseDir, document.document_dir);
    const sourcePath = fromRelative(baseDir, document.source_path);
    const markdownPath = fromRelative(baseDir, document.markdown_path);
    const itemsPath = fromRelative(baseDir, document.items_path);

    updateDocument(documentId, { status: 'copying', progress: 5, message: '正在复制原始文件' }, webContents);
    ensureDir(documentDir);
    await fsp.copyFile(sourceFilePath, sourcePath);

    updateDocument(documentId, { status: 'converting', progress: 15, message: '正在转换为 Markdown' }, webContents);
    const markdown = (await convertPathToMarkdown(sourcePath, { includeImages: false })).trim();
    if (!markdown) throw new Error('文档未解析出有效 Markdown 内容');
    await fsp.writeFile(markdownPath, `${markdown}\n`, 'utf-8');

    const blocks = createMarkdownBlocks(markdown);
    const blockMap = new Map(blocks.map((block) => [block.id, block]));
    const chunks = createChunks(blocks);
    const decisions = [];

    for (let index = 0; index < chunks.length; index += 1) {
      const progress = Math.min(95, 35 + Math.round(((index + 1) / chunks.length) * 55));
      updateDocument(documentId, { status: 'analyzing', progress, message: `AI 正在整理资料 ${index + 1}/${chunks.length}` }, webContents);
      const parsed = await aiService.collectJsonResponse({
        messages: buildDecisionMessages(document.file_name, index, chunks.length, renderAnnotatedBlocks(chunks[index])),
        temperature: 0.2,
        response_format: { type: 'json_object' },
        normalizer: (value) => ({ items: normalizeDecisionItems(value) }),
        validator: validateDecisionItems,
        failureMessage: '知识库资料整理失败，AI 未返回有效 JSON',
        progressLabel: '知识库整理',
      });
      decisions.push(...normalizeDecisionItems(parsed));
    }

    updateDocument(documentId, { status: 'saving', progress: 96, message: '正在保存知识条目' }, webContents);
    const items = buildKnowledgeItems(decisions, blockMap, document.file_name);
    await fsp.writeFile(itemsPath, JSON.stringify(items, null, 2), 'utf-8');
    updateDocument(documentId, { status: 'success', progress: 100, message: `整理完成，共 ${items.length} 条`, item_count: items.length }, webContents);
  }

  return {
    list() {
      return loadIndex();
    },

    createFolder(name) {
      const index = loadIndex();
      const folder = { id: createId('folder'), name: safeName(name), created_at: now(), updated_at: now() };
      saveIndex({ ...index, folders: [...index.folders, folder] });
      return folder;
    },

    async uploadDocuments(folderId, webContents) {
      const currentIndex = loadIndex();
      const folder = currentIndex.folders.find((item) => item.id === folderId);
      if (!folder) throw new Error('请先选择知识库文件夹');

      const result = await dialog.showOpenDialog({
        title: '选择知识库文档',
        properties: ['openFile', 'multiSelections'],
        filters: [
          { name: '知识库文档', extensions: ['doc', 'docx', 'wps', 'pdf', 'md', 'markdown'] },
          { name: '所有文件', extensions: ['*'] },
        ],
      });

      if (result.canceled || !result.filePaths.length) {
        return { success: false, message: '已取消选择' };
      }

      const created = [];
      let index = loadIndex();
      for (const filePath of result.filePaths) {
        const ext = path.extname(filePath).toLowerCase();
        if (!supportedExtensions.has(ext)) continue;
        const documentId = createId('doc');
        const documentDir = path.join('folders', folderId, 'documents', documentId);
        const sourceName = `source${ext}`;
        const document = {
          id: documentId,
          folder_id: folderId,
          file_name: path.basename(filePath),
          document_dir: documentDir,
          source_path: path.join(documentDir, sourceName).replace(/\\/g, '/'),
          markdown_path: path.join(documentDir, 'content.md').replace(/\\/g, '/'),
          items_path: path.join(documentDir, 'items.json').replace(/\\/g, '/'),
          status: 'pending',
          progress: 0,
          message: '等待处理',
          item_count: 0,
          created_at: now(),
          updated_at: now(),
        };
        index = saveIndex({ ...index, documents: [...index.documents, document] });
        created.push(document);
        emitProgress(webContents, document);
        processDocument(documentId, filePath, webContents).catch((error) => {
          updateDocument(documentId, { status: 'error', progress: 100, message: error.message || '处理失败', error: error.message || '处理失败' }, webContents);
        });
      }

      return { success: true, message: `已加入 ${created.length} 个文档处理任务`, documents: created };
    },

    readMarkdown(documentId) {
      const index = loadIndex();
      const document = index.documents.find((item) => item.id === documentId);
      if (!document) throw new Error('知识库文档不存在');
      const filePath = fromRelative(baseDir, document.markdown_path);
      return fs.existsSync(filePath) ? fs.readFileSync(filePath, 'utf-8') : '';
    },

    readItems(documentId) {
      const index = loadIndex();
      const document = index.documents.find((item) => item.id === documentId);
      if (!document) throw new Error('知识库文档不存在');
      return readJson(fromRelative(baseDir, document.items_path), []);
    },
  };
}

module.exports = { createKnowledgeBaseService };
