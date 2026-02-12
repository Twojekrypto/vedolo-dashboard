---
name: web-dashboard-development
description: >
  Buduje i dopracowuje single-page dashboardy HTML/CSS/JS z ciemnym motywem,
  interaktywnymi wykresami canvas, responsywnym layoutem i deploy na GitHub Pages.
  Użyj gdy użytkownik prosi o "dashboard", "stronę ze statystykami",
  "wykres", "tabele z danymi", "responsywny layout", "dark mode UI",
  "deploy na GitHub Pages" lub "popraw mobile view".
  NIE używaj do aplikacji React/Vue/Next.js, backendów API ani baz danych.
metadata:
  author: Adam Szybki
  version: 1.0.0
---

# Web Dashboard Development

Skill do tworzenia i dopracowywania single-page dashboardów w czystym HTML/CSS/JS.

## Critical — Design System

### Kolor i motyw
- Zawsze dark mode: `background: #0a0a1a`, karty `rgba(255,255,255,0.03)`
- CSS variables dla kolorów akcentowych:
  ```css
  --accent-indigo: #6366f1;
  --accent-green: #34d399;
  --accent-amber: #FFA406;
  --accent-cyan: #22d3ee;
  --accent-orange: #fb923c;
  --accent-rose: #fb7185;
  ```
- Glassmorphism na kartach: `backdrop-filter: blur()`, subtelne bordery `rgba(255,255,255,0.06)`
- Gradient glow na hover: `box-shadow: 0 0 20px rgba(kolor, 0.3)`

### Typografia
- Font: Inter z Google Fonts, `font-feature-settings: 'cv01','cv02','cv03'`
- Metryki: 28-32px bold, labele: 11px uppercase z `letter-spacing: 0.8px`
- Subteksty: muted color (`rgba(255,255,255,0.4)`)

### Layout
- `metrics-strip`: CSS Grid `repeat(auto-fit, minmax(180px, 1fr))`
- Karty: `border-radius: 16px`, padding 24px
- Animacje wejścia: `@keyframes fadeSlideUp` z opóźnieniami per element

## Important — Responsywność (Mobile)

### Media queries — standard
```css
@media (max-width: 1024px) { /* 3 kolumny */ }
@media (max-width: 768px)  { /* 2 kolumny, stacked layout */ }
@media (max-width: 480px)  { /* mniejsze fonty */ }
```

### Znane pułapki na mobile
1. **Tabele** — dodaj `overflow-x: auto` na kontener, ustaw `min-width` na table
2. **Canvas wykresy** — ustaw `min-width: 600px` na canvas + `overflow-x: auto` na kontener scrollujący
3. **Grid z nieparzystą liczbą elementów** — ostatni element sam w wierszu:
   ```css
   .metric-cell:last-child:nth-child(odd) {
       grid-column: 1 / -1;
   }
   ```
4. **Legendy wykresów** — `white-space: nowrap` żeby nie łamały się na kilka linii
5. **Tooltip icons** — zawsze resetuj odziedziczone style:
   ```css
   .tooltip-icon {
       font-style: normal;
       letter-spacing: 0;
       text-transform: none;
   }
   ```

## Instrukcje — Tooltips

### Struktura HTML (dwa wzorce)
```html
<!-- Wzorzec 1: bubble wewnątrz icon (veDOLO) -->
<span class="tooltip-icon">?
    <span class="tooltip-bubble">Tekst wyjaśnienia</span>
</span>

<!-- Wzorzec 2: bubble jako sibling (oDOLO) -->
<span class="tooltip-wrap">
    LABEL
    <i class="tooltip-icon">?</i>
    <span class="tooltip-bubble">Tekst wyjaśnienia</span>
</span>
```

### CSS musi obsługiwać oba wzorce
```css
.tooltip-icon:hover .tooltip-bubble,
.tooltip-wrap:hover .tooltip-bubble {
    display: block;
}
```

### Click-to-stay (dla tooltipów z linkami)
Jeśli tooltip zawiera klikalne linki, dodaj JS toggle z klasą `.active`:
- `pointer-events: auto` na tooltip
- `e.stopPropagation()` na click handlera
- Zamykaj na click poza elementem

## Instrukcje — Canvas Charts

### Rendering na canvas
1. Zawsze obsłuż `devicePixelRatio`:
   ```javascript
   const dpr = window.devicePixelRatio || 1;
   canvas.width = canvas.offsetWidth * dpr;
   canvas.height = canvas.offsetHeight * dpr;
   ctx.scale(dpr, dpr);
   ```
2. Responsywne padding: sprawdzaj `isMobile = W < 500`
3. Hover interakcja: zapisuj pozycje elementów w tablicy, sprawdzaj hit detection w mousemove
4. Tooltip: absolutnie pozycjonowany div, aktualizuj position w handlera move

### Filtrowanie danych
- Wykresy timeline: **zawsze filtruj przeszłe daty** (`if (timestamp < now) return`)
- Używaj `Date.now() / 1000` na bieżąco, nie cache'uj

### Cross-highlighting (wykres ↔ legenda)
```javascript
// Hover na segment → highlight legenda i vice versa
// Dim inne elementy: opacity 0.3-0.4
// Highlight aktywny: background rgba, border-left, bold text
```

## Instrukcje — Deployment (GitHub Pages)

### Workflow deploy
```bash
# 1. Edytuj ZAWSZE index_draft.html (plik roboczy)
# 2. Kopiuj do index.html (plik produkcyjny)
cp index_draft.html index.html
# 3. Commit i push
git add index.html [inne nowe pliki]
git commit -m "Opis zmiany"
git push origin main
```

### Checklist przed pushem
- [ ] Wszystkie assety (SVG, JSON) są w git (`git ls-files --others`)
- [ ] Pliki danych (`.json`) referenced w kodzie są commitowane
- [ ] Logo/ikony SVG są w repozytorium
- [ ] `index.html` jest zaktualizowany z `index_draft.html`

## Troubleshooting

### Tooltip nie działa
- **Przyczyna:** Bubble jest siblingiem icon, nie child
- **Rozwiązanie:** Dodaj regułę `.tooltip-wrap:hover .tooltip-bubble`
- **Przyczyna 2:** Brak `position: relative` na rodzicu
- **Rozwiązanie:** Dodaj `.tooltip-wrap { position: relative }`

### Ikona (?) krzywa/pochylona
- **Przyczyna:** Tag `<i>` lub odziedziczony `letter-spacing`/`text-transform`
- **Rozwiązanie:** `font-style: normal; letter-spacing: 0; text-transform: none`

### Brak danych/logo na GitHub Pages
- **Przyczyna:** Pliki nie zostały commitowane (są w `.gitignore` lub untracked)
- **Rozwiązanie:** `git ls-files --others` → `git add` brakujące pliki

### Wykres rozjechany na mobile
- **Przyczyna:** Za dużo elementów w małej szerokości
- **Rozwiązanie:** `min-width: 600px` na canvas + `overflow-x: auto` na kontener

### Push rejected
- **Przyczyna:** Remote ma nowsze commity
- **Rozwiązanie:** `git pull --rebase origin main` → `git push origin main`

## Przykłady

### Przykład 1: Dodawanie nowej metryki
Użytkownik mówi: "Dodaj metrykę AVG DISCOUNT"
1. Dodaj `<div class="metric-cell">` z label, value, sub
2. Dodaj odpowiednią klasę koloru: `class="metric-value green"`
3. Sprawdź czy klasa CSS istnieje (`.metric-value.green`)
4. Dodaj tooltip z wyjaśnieniem
5. Dodaj JS do wypełniania wartości
6. Przetestuj mobile — czy grid się nie rozjechał

### Przykład 2: Naprawa mobile layout
Użytkownik mówi: "Wykres się rozjeżdża na telefonie"
1. Zidentyfikuj element (canvas/tabela/grid)
2. Dla canvas: `min-width: 600px` + scroll kontener
3. Dla tabeli: `overflow-x: auto` na wrapper
4. Dla grid: sprawdź czy ostatni element nie jest sam (`nth-child(odd)`)
5. Testuj w viewporcie 375x812

### Przykład 3: Deploy zmian
Użytkownik mówi: "Zaktualizuj stronę na GitHub"
1. `cp index_draft.html index.html`
2. `git ls-files --others` — sprawdź brakujące pliki
3. `git add` wszystkie potrzebne pliki
4. `git commit -m "Opis"` → `git push origin main`
5. Jeśli rejected: `git pull --rebase` najpierw
