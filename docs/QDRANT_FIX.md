# Qdrant: Fix de storage corrupto / sin persistencia

Si ves errores tipo:

- `failed to open file ... mutable_id_tracker.mappings: No such file or directory`
- `Can't create directory for collection ... No such file or directory`
- `Error: 500 Internal Server Error` al indexar PDFs o al chatear

casi siempre es porque el *storage* de Qdrant está:

1) dentro de la carpeta del proyecto y se borró/reescribió al actualizar el código, o  
2) tiene permisos incorrectos, o  
3) se corrompió (apagado brusco / carpeta incompleta).

## Opción A (rápida): resetear y reindexar

> **Esto borra el vector DB**. Vas a tener que re-indexar PDFs.

1. Detén el contenedor:
   ```bash
   docker rm -f qdrant
   ```

2. Mueve/borra el storage anterior (si estaba dentro del proyecto):
   ```bash
   sudo mv /home/ec2-user/rag_prod/qdrant_storage /home/ec2-user/qdrant_storage_BACKUP_$(date +%F_%H%M%S) || true
   ```

3. Levanta Qdrant con storage persistente fuera del repo:
   ```bash
   cd /home/ec2-user/rag_prod
   ./docker/run_qdrant.sh
   ```

4. Verifica:
   ```bash
   curl -s http://127.0.0.1:6333/collections
   docker logs -f qdrant
   ```

5. Re-indexa desde la app (PDFs permanentes / temporales).

## Opción B: usar Docker Volume (recomendado)

En lugar de bind-mount a un folder, puedes usar un volumen:

```bash
docker volume create qdrant_data
docker rm -f qdrant || true
docker run -d --name qdrant -p 6333:6333 -p 6334:6334 -v qdrant_data:/qdrant/storage qdrant/qdrant:latest
```

Esto es mucho más resistente a despliegues y backups.
