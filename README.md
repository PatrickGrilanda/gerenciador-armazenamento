# Gerenciador de Armazenamento (Windows)

Aplicativo desktop para analisar o que ocupa espaço em cada volume do Windows (incluindo discos externos) e desinstalar programas pelo assistente oficial.

Repositório: [github.com/PatrickGrilanda/gerenciador-armazenamento](https://github.com/PatrickGrilanda/gerenciador-armazenamento)

## Download (usuário final)

1. Abra [Releases](https://github.com/PatrickGrilanda/gerenciador-armazenamento/releases).
2. Baixe o arquivo **`GerenciadorArmazenamento-Setup-x.y.z.exe`** da versão mais recente.
3. Execute o instalador e use o atalho no menu Iniciar.

Dentro do app, use **Verificar atualizações** (barra lateral ou aba **Atualizações**) para baixar e instalar novas versões publicadas no GitHub.

## Desenvolvimento (Python)

Requisitos: Windows 10/11, Python 3.10+.

```powershell
cd gerenciador-armazenamento
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python run.py
```

## Build local do instalador (Windows)

```powershell
pip install -r requirements.txt pyinstaller==6.11.1
pyinstaller --noconfirm packaging/storage_manager.spec
# Instale Inno Setup 6 e execute:
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" /DMyAppVersion=1.0.0 installer\setup.iss
```

O instalador sai em `dist/installer/`.

## Publicar versão

Veja [RELEASES.md](RELEASES.md).
