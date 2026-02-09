# Deploy con Git (VS Code → EC2) + Rollback fácil

La idea es que **el código viva en Git** y la instancia (EC2) solo haga `git pull` + restart servicios.
Así evitas subir ZIPs y reduces el riesgo de romper Qdrant / .env.

## 1) En tu PC (VS Code)

1. Inicializa repo (si no lo hiciste):
   ```bash
   git init
   git add .
   git commit -m "Initial"
   ```

2. Crea el repositorio remoto (GitHub / GitLab / Bitbucket).

3. Conecta el remoto y sube:
   ```bash
   git remote add origin <URL>
   git branch -M main
   git push -u origin main
   ```

### Recomendación: no versionar secretos

Asegúrate de tener un `.gitignore` con:
- `.env`
- `.venv/`
- `__pycache__/`
- `qdrant_storage/` (¡muy importante!)
- `chat_store.db` (si lo guardas local)

## 2) En la EC2 (instancia)

### Opción simple (un solo folder)
1. Clona el repo en una ruta estable:
   ```bash
   cd /home/ec2-user
   git clone <URL> rag_prod
   cd rag_prod
   ```

2. Crea `.env` en el servidor (NO lo subas a git):
   ```bash
   nano .env
   ```

3. Instala dependencias (ideal en venv):
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

4. Reinicia servicios:
   ```bash
   sudo systemctl restart rag-api
   sudo systemctl restart rag-ui
   sudo systemctl restart nginx
   ```

### Rollback (volver a versiones anteriores)
Cuando algo sale mal:

1. Lista commits:
   ```bash
   git log --oneline --decorate -n 20
   ```

2. Vuelve a un commit:
   ```bash
   git checkout <HASH>
   sudo systemctl restart rag-api rag-ui nginx
   ```

> Mejor aún: usa **tags** para versiones (v1.0, v1.1)

```bash
git tag -a v1.1 -m "release v1.1"
git push origin v1.1
```

Luego en EC2:
```bash
git fetch --tags
git checkout v1.1
sudo systemctl restart rag-api rag-ui nginx
```

## 3) Estrategia pro (releases + symlink)

Para despliegues más seguros, usa:

- `/opt/viva_rag/releases/<fecha>/` → cada deploy
- `/opt/viva_rag/current` → symlink al release activo

Rollback = cambiar symlink y reiniciar servicios.

Si quieres, te armo el script de releases.

## 4) Evitar romper Qdrant en deploys

NO guardes el storage dentro del repo. Usa:

- `/opt/qdrant_storage` (bind mount), o
- `docker volume qdrant_data`

Ver `docs/QDRANT_FIX.md`.
