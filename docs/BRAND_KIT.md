# Viva AI Assistant — Kit de Marca (propuesto)

Este *kit* está pensado para mantener una estética consistente en:

- Streamlit (UI)
- Login / Embed (páginas estáticas)
- Componentes (botones, cards, pills)

## Colores

**Background**
- `--viva-bg`: `#0b0e14`
- `--viva-bg-2`: `#121826`

**Superficies**
- `--viva-surface`: `rgba(255,255,255,0.06)`
- `--viva-surface-2`: `rgba(255,255,255,0.10)`

**Bordes**
- `--viva-border`: `rgba(255,255,255,0.10)`

**Texto**
- `--viva-text`: `rgba(255,255,255,0.92)`
- `--viva-muted`: `rgba(255,255,255,0.66)`

**Accentos**
- `--viva-accent`: `#ff2d55` (principal)
- `--viva-accent-2`: `#6ee7ff` (secundario / links)

## Tipografía

- Por defecto: `system-ui` (nativa, rápida, sin dependencias)
- Si quieres algo más "marca": puedes cargar *Inter* desde Google Fonts en Nginx o dentro de Streamlit, pero es opcional.

## Componentes UI

- **Card**: fondo `--viva-surface`, borde `--viva-border`, radio `--viva-radius`
- **Pill**: chip/pastilla para usuario/estado
- **Botón**:
  - normal: fondo translúcido
  - primary: gradiente `accent` → `#ff7a18`

## Logo

En este bundle dejamos un placeholder en:

- `web/assets/logo.svg`

Puedes reemplazarlo por tu SVG/PNG manteniendo el nombre, o cambiarlo en:
- `web/login/index.html`
- `web/embed/index.html`
