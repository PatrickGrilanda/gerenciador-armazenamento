# Publicar uma nova versão

1. Atualize `storage_manager/__init__.py` (`__version__`) no repositório (opcional para documentação; o CI usa a tag).
2. Faça commit das mudanças na branch `main`.
3. Crie e envie uma tag semver:

```bash
git tag v1.0.1
git push origin main
git push origin v1.0.1
```

4. O workflow **Release** (`.github/workflows/release.yml`) compila o `.exe`, gera o instalador Inno Setup e publica em [GitHub Releases](https://github.com/PatrickGrilanda/gerenciador-armazenamento/releases).

O aplicativo instalado verifica `releases/latest` e baixa o arquivo `GerenciadorArmazenamento-Setup-<versão>.exe`.
