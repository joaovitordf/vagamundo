# Política de Segurança

## Relato de Vulnerabilidades

Caso identifique qualquer falha de segurança, problema de privacidade ou vulnerabilidade no Vagamundo, por favor reporte através das [Issues do GitHub](https://github.com/joaovitordf/vagamundo/issues) ou contate o mantenedor diretamente.

---

## Modelo de Segurança e Privacidade

O Vagamundo foi desenhado sob o princípio de **execução local prioritária (Local-First)**:

1. **Isolamento de Credenciais e Segredos:**
   - Chaves de API (`GEMINI_API_KEY`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`) residem exclusivamente no arquivo `.env` local, o qual é rigidamente ignorado pelo Git (`.gitignore`).
   - O banco de dados SQLite (`data/vagamundo.db`) e uploads pessoais (`documents/cv/`, `documents/linkedin/`) nunca são versionados.

2. **Tratamento de Dados de Vagas (Untrusted Data):**
   - Vagas coletadas da web são tratadas estritamente como **dados de entrada** e nunca como instruções executáveis para os modelos de IA.
   - O sistema filtra scripts maliciosos, instruções embutidas e caracteres ocultos via `posting_guard.py` antes do processamento.

3. **Permissões de Execução:**
   - Cada CLI de portal opera em seu próprio escopo em `.agents/skills/<nome>/cli/`.
   - Manifestos `package.json` das CLIs não utilizam scripts de ciclo de vida arbitrários (`preinstall`/`postinstall`).

4. **Compilação Segura de Documentos:**
   - As rotinas de compilação de LaTeX desativam a execução de comandos externos no shell (`--disable-write18` no MiKTeX e `-no-shell-escape` no TeX Live).
