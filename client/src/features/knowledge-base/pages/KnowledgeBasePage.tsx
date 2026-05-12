import { useEffect, useMemo, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import rehypeRaw from 'rehype-raw';
import remarkGfm from 'remark-gfm';
import { useToast } from '../../../shared/ui';
import type { KnowledgeBaseIndex, KnowledgeDocument, KnowledgeItem } from '../types';

const emptyIndex: KnowledgeBaseIndex = { folders: [], documents: [] };

const statusLabels: Record<KnowledgeDocument['status'], string> = {
  pending: '等待处理',
  copying: '复制文件',
  converting: '转换 Markdown',
  analyzing: 'AI 整理中',
  saving: '保存结果',
  success: '完成',
  error: '失败',
};

type KnowledgeViewer = {
  document: KnowledgeDocument;
  mode: 'items' | 'markdown';
};

function KnowledgeBasePage() {
  const [index, setIndex] = useState<KnowledgeBaseIndex>(emptyIndex);
  const [activeFolderId, setActiveFolderId] = useState('');
  const [loading, setLoading] = useState(false);
  const [viewer, setViewer] = useState<KnowledgeViewer | null>(null);
  const [markdownPreview, setMarkdownPreview] = useState('');
  const [itemsPreview, setItemsPreview] = useState<KnowledgeItem[]>([]);
  const [showCreateFolder, setShowCreateFolder] = useState(false);
  const [newFolderName, setNewFolderName] = useState('');
  const [creatingFolder, setCreatingFolder] = useState(false);
  const { showToast } = useToast();

  const activeFolder = index.folders.find((folder) => folder.id === activeFolderId) || index.folders[0];
  const documents = useMemo(
    () => index.documents.filter((document) => document.folder_id === activeFolder?.id),
    [activeFolder?.id, index.documents]
  );

  useEffect(() => {
    void loadIndex();
    const unsubscribe = window.yibiao?.knowledgeBase.onEvent(({ document }) => {
      setIndex((prev) => ({
        ...prev,
        documents: prev.documents.some((item) => item.id === document.id)
          ? prev.documents.map((item) => (item.id === document.id ? document : item))
          : [...prev.documents, document],
      }));
      setViewer((prev) => (prev?.document.id === document.id ? { ...prev, document } : prev));
    });
    return () => unsubscribe?.();
  }, []);

  useEffect(() => {
    if (!activeFolderId && index.folders[0]) {
      setActiveFolderId(index.folders[0].id);
    }
  }, [activeFolderId, index.folders]);

  const loadIndex = async () => {
    try {
      const data = await window.yibiao?.knowledgeBase.list();
      if (data) setIndex(data);
    } catch (error) {
      showToast(error instanceof Error ? error.message : '读取知识库失败', 'error');
    }
  };

  const createFolder = async () => {
    const name = newFolderName.trim();
    if (!name) {
      showToast('请输入文件夹名称', 'info');
      return;
    }

    try {
      setCreatingFolder(true);
      const folder = await window.yibiao?.knowledgeBase.createFolder(name.trim());
      if (!folder) return;
      setIndex((prev) => ({ ...prev, folders: [...prev.folders, folder] }));
      setActiveFolderId(folder.id);
      setNewFolderName('');
      setShowCreateFolder(false);
      showToast('文件夹已创建', 'success');
    } catch (error) {
      showToast(error instanceof Error ? error.message : '创建文件夹失败', 'error');
    } finally {
      setCreatingFolder(false);
    }
  };

  const uploadDocuments = async () => {
    if (!activeFolder) {
      showToast('请先创建文件夹', 'info');
      return;
    }

    try {
      setLoading(true);
      const result = await window.yibiao?.knowledgeBase.uploadDocuments(activeFolder.id);
      if (!result?.success) {
        showToast(result?.message || '未选择文档', 'info');
        return;
      }
      if (result.documents?.length) {
        setIndex((prev) => ({ ...prev, documents: mergeDocuments(prev.documents, result.documents || []) }));
      }
      showToast(result.message, 'success');
    } catch (error) {
      showToast(error instanceof Error ? error.message : '上传文档失败', 'error');
    } finally {
      setLoading(false);
    }
  };

  const openDocument = async (document: KnowledgeDocument, mode: 'items' | 'markdown') => {
    setViewer({ document, mode });
    setMarkdownPreview('');
    setItemsPreview([]);

    try {
      if (mode === 'markdown') {
        const markdown = await window.yibiao?.knowledgeBase.readMarkdown(document.id);
        setMarkdownPreview(markdown || '');
      } else {
        const items = await window.yibiao?.knowledgeBase.readItems(document.id);
        setItemsPreview(items || []);
      }
    } catch (error) {
      showToast(error instanceof Error ? error.message : '读取文档结果失败', 'error');
    }
  };

  if (viewer) {
    return (
      <KnowledgeDocumentViewer
        document={viewer.document}
        mode={viewer.mode}
        itemsPreview={itemsPreview}
        markdownPreview={markdownPreview}
        onBack={() => setViewer(null)}
        onModeChange={(mode) => void openDocument(viewer.document, mode)}
      />
    );
  }

  return (
    <div className="page-stack knowledge-page">
      <section className="knowledge-workspace-bar">
        <div className="knowledge-breadcrumb">
          <span>知识库</span>
          <strong>{activeFolder?.name || '未选择文件夹'}</strong>
          <small>{index.folders.length} 个文件夹 / {index.documents.length} 个文档</small>
        </div>
        <div className="knowledge-toolbar-actions">
          <button type="button" className="secondary-action" onClick={() => setShowCreateFolder((value) => !value)}>新建文件夹</button>
          <button type="button" className="primary-action" onClick={uploadDocuments} disabled={loading || !activeFolder}>
            {loading ? '处理中...' : '上传文档'}
          </button>
        </div>
      </section>

      {showCreateFolder && (
        <form
          className="knowledge-create-folder-bar"
          onSubmit={(event) => {
            event.preventDefault();
            void createFolder();
          }}
        >
          <input
            autoFocus
            value={newFolderName}
            onChange={(event) => setNewFolderName(event.target.value)}
            placeholder="输入文件夹名称"
          />
          <button type="submit" className="primary-action" disabled={creatingFolder}>{creatingFolder ? '创建中...' : '创建'}</button>
          <button
            type="button"
            className="secondary-action"
            onClick={() => {
              setNewFolderName('');
              setShowCreateFolder(false);
            }}
          >
            取消
          </button>
        </form>
      )}

      <section className="knowledge-layout">
        <aside className="knowledge-folder-panel">
          <div className="knowledge-panel-head">
            <strong>文件夹</strong>
            <span>{index.folders.length} 个</span>
          </div>
          {index.folders.length ? (
            <div className="knowledge-folder-list">
              {index.folders.map((folder) => {
                const count = index.documents.filter((document) => document.folder_id === folder.id).length;
                return (
                  <button
                    type="button"
                    key={folder.id}
                    className={`knowledge-folder-card ${folder.id === activeFolder?.id ? 'is-active' : ''}`}
                    onClick={() => setActiveFolderId(folder.id)}
                  >
                    <span aria-hidden="true">F</span>
                    <strong>{folder.name}</strong>
                    <small>{count} 个文档</small>
                  </button>
                );
              })}
            </div>
          ) : (
            <div className="knowledge-empty-box">
              <strong>还没有文件夹</strong>
              <p>先创建一个文件夹，再上传历史资料。</p>
            </div>
          )}
        </aside>

        <main className="knowledge-document-panel">
          <div className="knowledge-panel-head">
            <strong>{activeFolder?.name || '未选择文件夹'}</strong>
            <span>{documents.length} 个文档</span>
          </div>

          {documents.length ? (
            <div className="knowledge-document-list">
              {documents.map((document) => (
                <article className="knowledge-document-card" key={document.id}>
                  <div className="knowledge-document-title">
                    <strong>{document.file_name}</strong>
                    <span className={`knowledge-status is-${document.status}`}>{statusLabels[document.status]}</span>
                  </div>
                  <div className="knowledge-progress-track" aria-label={`处理进度 ${document.progress}%`}>
                    <span style={{ width: `${Math.max(0, Math.min(100, document.progress || 0))}%` }} />
                  </div>
                  <div className="knowledge-document-meta">
                    <span>{document.message}</span>
                    <span>{document.item_count || 0} 条知识</span>
                  </div>
                  <div className="knowledge-document-actions">
                    <button type="button" onClick={() => void openDocument(document, 'items')} disabled={document.status !== 'success'}>查看条目</button>
                    <button type="button" onClick={() => void openDocument(document, 'markdown')} disabled={!['success', 'error'].includes(document.status)}>查看 Markdown</button>
                  </div>
                </article>
              ))}
            </div>
          ) : (
            <div className="knowledge-empty-box large">
              <strong>当前文件夹暂无文档</strong>
              <p>支持上传 .doc、.docx、.wps、.pdf、.md 文档。</p>
            </div>
          )}
        </main>
      </section>
    </div>
  );
}

interface KnowledgeDocumentViewerProps {
  document: KnowledgeDocument;
  mode: 'items' | 'markdown';
  itemsPreview: KnowledgeItem[];
  markdownPreview: string;
  onBack: () => void;
  onModeChange: (mode: 'items' | 'markdown') => void;
}

function KnowledgeDocumentViewer({
  document,
  mode,
  itemsPreview,
  markdownPreview,
  onBack,
  onModeChange,
}: KnowledgeDocumentViewerProps) {
  return (
    <div className="page-stack knowledge-viewer-page">
      <section className="knowledge-workspace-bar knowledge-viewer-bar">
        <div className="knowledge-breadcrumb">
          <span>知识库</span>
          <strong>{document.file_name}</strong>
          <small>{mode === 'items' ? `${document.item_count || 0} 条知识` : 'Markdown 原文'}</small>
        </div>
        <div className="knowledge-toolbar-actions">
          <button type="button" className="secondary-action" onClick={onBack}>返回知识库</button>
          <button type="button" className={`secondary-action ${mode === 'items' ? 'is-active' : ''}`} onClick={() => onModeChange('items')}>知识条目</button>
          <button type="button" className={`secondary-action ${mode === 'markdown' ? 'is-active' : ''}`} onClick={() => onModeChange('markdown')}>Markdown</button>
        </div>
      </section>

      <section className="knowledge-viewer-panel">
        {mode === 'items' ? (
          <div className="knowledge-item-list knowledge-viewer-item-list">
            {itemsPreview.length ? itemsPreview.map((item) => (
              <article className="knowledge-item-card" key={item.id}>
                <strong>{item.title}</strong>
                <p>{item.resume}</p>
                <details>
                  <summary>查看原文</summary>
                  <pre>{item.content}</pre>
                </details>
              </article>
            )) : <div className="knowledge-empty-box"><strong>暂无知识条目</strong><p>文档完成整理后会显示结果。</p></div>}
          </div>
        ) : (
          <div className="markdown-viewer knowledge-viewer-markdown">
            <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeRaw]}>
              {markdownPreview || '暂无 Markdown 内容'}
            </ReactMarkdown>
          </div>
        )}
      </section>
    </div>
  );
}

function mergeDocuments(prev: KnowledgeDocument[], next: KnowledgeDocument[]) {
  const byId = new Map(prev.map((document) => [document.id, document]));
  next.forEach((document) => byId.set(document.id, document));
  return Array.from(byId.values());
}

export default KnowledgeBasePage;
