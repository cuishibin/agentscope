import express from 'express';
import cors from 'cors';
import path from 'path';

const app = express();
const PORT = process.env.PORT || 3000;

app.use(cors());
app.use(express.json());

// 静态产物路径：dist/index.js 的 __dirname 为 backend/dist，
// 向上两级回到 web_ui 根，再进入 frontend/dist。
// 路径可用 FRONTEND_DIST 环境变量覆盖（容器/本地部署更灵活）。
const frontendDist =
	process.env.FRONTEND_DIST ??
	path.resolve(__dirname, '../../frontend/dist');

// 托管前端构建产物（方案 B：Express 单进程同时提供页面与 API）
app.use(express.static(frontendDist));

// SPA fallback：非 /api 路径统一回退到 index.html，交给前端路由。
// 用中间件而非路径正则，规避 Express 版本间正则行为差异。
app.use((req, res, next) => {
	if (req.method === 'GET' && !req.path.startsWith('/api')) {
		res.sendFile(path.join(frontendDist, 'index.html'));
		return;
	}
	next();
});

app.get('/api/health', (_req, res) => {
	res.json({ status: 'ok' });
});

app.listen(PORT, () => {
	console.log(`Server running on http://localhost:${PORT}`);
});
