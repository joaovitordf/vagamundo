# Vagamundo — Frontend SPA

Interface web moderna do Vagamundo, desenvolvida em **Angular 17+** com arquitetura baseada em componentes standalone e Angular Signals.

## Tecnologias e Arquitetura

- **Angular 17+** com TypeScript
- **Componentes Standalone** (sem NgModule)
- **Reatividade com Signals**: `signal`, `computed`, `effect`
- **Proxy de Desenvolvimento**: `proxy.conf.json` direciona chamadas de `/api/*` para o backend FastAPI em `http://127.0.0.1:8765/`
- **Design Responsivo & Dark Mode**: Interface otimizada com visualização em cards, tabelas dinâmicas e mapas interativos (SVG/Canvas).

## Como Executar

### Junto com o Backend (Recomendado)
A partir da raiz do repositório:
```bash
npm run dev
```

### Isoladamente (Apenas o Frontend)
```bash
cd frontend
npm install
npm start
```
Acesse em: `http://localhost:4200/`

## Compilação de Produção
```bash
npm run build
```
Os arquivos gerados são emitidos no diretório `dist/frontend`.
