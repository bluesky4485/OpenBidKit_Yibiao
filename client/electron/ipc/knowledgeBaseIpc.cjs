const { ipcMain } = require('electron');

function registerKnowledgeBaseIpc({ knowledgeBaseService }) {
  ipcMain.handle('knowledge-base:list', () => knowledgeBaseService.list());
  ipcMain.handle('knowledge-base:create-folder', (_event, name) => knowledgeBaseService.createFolder(name));
  ipcMain.handle('knowledge-base:upload-documents', (event, folderId) => knowledgeBaseService.uploadDocuments(folderId, event.sender));
  ipcMain.handle('knowledge-base:read-markdown', (_event, documentId) => knowledgeBaseService.readMarkdown(documentId));
  ipcMain.handle('knowledge-base:read-items', (_event, documentId) => knowledgeBaseService.readItems(documentId));
}

module.exports = { registerKnowledgeBaseIpc };
