# JellyNews v1.0.2 — Direction artistique Aï

## Concept : Media Current

JellyNews doit passer de “portail admin sombre” à “cabine de projection qui prépare une newsletter”. La direction garde l’ADN Jellyfin/ElegantFin (fond profond, cartes arrondies, accent bleu), mais ajoute un courant visuel cyan/violet qui relie trois idées : médias Jellyfin, flux hebdomadaire, envoi aux abonnés.

Mots-clés : médiathèque nocturne, courant bioluminescent, newsletter fiable, admin sobre, affiches et historique lisibles.

## Palette

| Token | Hex | Usage |
|---|---:|---|
| `--jn-bg-deep` | `#07111f` | fond principal, plus riche que le noir actuel |
| `--jn-bg` | `#0b1626` | corps de page / zones larges |
| `--jn-surface` | `#101c2d` | sidebar, cartes principales |
| `--jn-surface-raised` | `#162336` | inputs, tables, blocs secondaires |
| `--jn-border` | `#20344a` | séparateurs sobres |
| `--jn-border-hot` | `#2f80b7` | focus, hover, active léger |
| `--jn-text` | `#f2f7fb` | texte principal |
| `--jn-muted` | `#9fb0c3` | aides, labels secondaires |
| `--jn-cyan` | `#00f5d4` | accent “courant / succès / newsletter” |
| `--jn-blue` | `#00a4dc` | accent Jellyfin / action primaire |
| `--jn-violet` | `#7c4dff` | profondeur Jellyfin / sélection |
| `--jn-gold` | `#ffe66d` | rare : notification, prochain envoi |
| `--jn-danger` | `#ff6b7a` | erreur / suppression |
| `--jn-ok` | `#4ee59d` | statut OK |

Contraste vérifié par calcul : `#f2f7fb` sur `#07111f`, `#9fb0c3` sur `#07111f`, `#07111f` sur `#00f5d4`, `#f2f7fb` sur `#162336`, `#ff6b7a` sur `#07111f` passent AA normal.

## Typographie

Rester sans dépendance externe :

```css
font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
```

Si l’app reste 100 % locale/offline, ne pas charger Google Fonts. Si Motoko veut un léger upgrade sans dépendance, utiliser `letter-spacing: -0.02em` sur les titres et des chiffres tabulaires sur tables/logs : `font-variant-numeric: tabular-nums;`.

## Structure visuelle

1. Sidebar “station”
   - largeur 248 px desktop ; 72 px possible en mode compact futur ; sticky conservé ;
   - logo `jellynews-mark.svg` + nom ; éviter l’emoji comme seul repère produit ;
   - nav en pills avec icône unicode contrôlée ou petit SVG inline, pas d’images générées ;
   - item actif : dégradé violet→bleu, petit liseré cyan à gauche.

2. Main “flux”
   - largeur utile 920–1040 px au lieu de 860 px pour les tables ;
   - fond radial discret via `media-current-bg.svg` en haut à droite, `opacity` faible ;
   - chaque panel commence par un en-tête : titre + microcopy + badge d’état si disponible.

3. Formulaires
   - labels plus hiérarchisés : label 14 px / aide 13 px ;
   - inputs `44px` min-height ; focus ring cyan 2 px ;
   - groupes `.field-grid` responsive : 2/3 colonnes desktop, 1 colonne mobile.

4. Tables / logs
   - tables dans une carte `.table-shell` avec overflow horizontal ;
   - header sticky optionnel ;
   - statuts en badges, pas seulement texte coloré ;
   - actions “Voir”, “Exporter”, “Importer” alignées avec boutons secondaires.

5. Newsletter preview / actions
   - bouton primaire “Envoyer maintenant” bleu→cyan ; bouton preview secondaire ;
   - bloc “Dernier envoi” ou “Prochain envoi” en carte KPI si Motoko expose les données.

## Tokens CSS proposés

```css
:root {
  color-scheme: dark;
  --jn-bg-deep: #07111f;
  --jn-bg: #0b1626;
  --jn-surface: #101c2d;
  --jn-surface-raised: #162336;
  --jn-border: #20344a;
  --jn-border-hot: #2f80b7;
  --jn-text: #f2f7fb;
  --jn-muted: #9fb0c3;
  --jn-cyan: #00f5d4;
  --jn-blue: #00a4dc;
  --jn-violet: #7c4dff;
  --jn-gold: #ffe66d;
  --jn-danger: #ff6b7a;
  --jn-ok: #4ee59d;
  --jn-radius-sm: 10px;
  --jn-radius-md: 14px;
  --jn-radius-lg: 22px;
  --jn-shadow-soft: 0 18px 60px rgba(0, 8, 22, .34);
  --jn-focus: 0 0 0 3px rgba(0, 245, 212, .22);
  --jn-gradient-primary: linear-gradient(135deg, #7c4dff 0%, #00a4dc 58%, #00f5d4 100%);
}
```

Compatibilité avec le CSS actuel : les tokens peuvent cohabiter avec les variables existantes en alias progressif : `--bg: var(--jn-bg-deep)`, etc. Pas besoin de framework.

## Composants recommandés

- `.brand-lockup` : mark 32×32 + “JellyNews” + sous-label “media digest”.
- `.panel-heading` : titre + description courte. Exemple Jellyfin : “Connectez votre médiathèque et choisissez ce qui entre dans le courant hebdomadaire.”
- `.metric-card` : prochain envoi, abonnés, nouveautés trouvées, dernier statut.
- `.status-pill.is-ok|is-error|is-skipped` : badges de logs.
- `.table-shell` : carte autour des tables avec `overflow-x: auto`.
- `.empty-state` : utiliser `empty-media-mail.svg` quand abonnés/logs/archives sont vides.
- `.current-divider` : ligne décorative cyan/violet très faible entre sections longues.

## Assets produits

- `app/static/brand/jellynews-mark.svg` — symbole produit SVG-first, transparent, sans texte ; utilisable en logo sidebar, favicon source et avatar d’app.
- `app/static/brand/media-current-bg.svg` — fond décoratif abstrait, sans texte, à poser en `background-image` avec faible opacité.
- `app/static/brand/empty-media-mail.svg` — illustration d’état vide, sans texte, pour abonnés/logs/archives.
- `docs/design/jellynews-v1.0.2-preview.html` — prototype statique de la direction, sans dépendance externe.
- `docs/design/jellynews-mark-kit/` — exports générés depuis le SVG source : PNG favicons, `.ico`, apple-touch, manifest snippet, planche de contrôle.

## Responsive

- `@media (max-width: 780px)` : layout en colonne ; sidebar devient topbar horizontale scrollable ; `height: auto`; nav en ligne.
- `@media (max-width: 640px)` : padding content 20 px ; tous les grids en 1 colonne ; `.row` en colonne sauf actions critiques ; boutons pleine largeur seulement dans auth/mobile.
- Tables : toujours enveloppées dans `.table-shell { overflow-x:auto; }`; ne pas réduire les colonnes de logs au point de casser les dates.

## Accessibilité

- Garder un vrai texte “JellyNews” à côté du mark ; l’icône seule ne suffit pas.
- Focus visible : ring cyan, jamais uniquement changement de couleur.
- Ne pas utiliser le cyan sur fond clair ; sur fond sombre il est très lisible.
- Le violet `#7c4dff` seul sur fond sombre est décoratif ; pour texte interactif préférer `#7dd3fc` ou `#00f5d4`.
- Respecter `prefers-reduced-motion`: pas de courant animé obligatoire ; si animation future, durée lente et désactivable.

## Handoff Motoko

Checklist d’intégration KISS :

1. Ajouter les assets SVG sous `/static/brand/` et utiliser `jellynews-mark.svg` dans `login.html`, `setup.html`, `dashboard.html`.
2. Remplacer les variables actuelles de `style.css` par les aliases `--jn-*` sans toucher à la logique JS.
3. Ajouter les wrappers `.panel-heading`, `.table-shell`, `.status-pill` directement dans les templates existants ; ne pas introduire de build step.
4. Mettre les tables logs/archives dans `.table-shell` pour le responsive.
5. Conserver l’email template plus strict : lui appliquer seulement la palette compatible email, pas le fond SVG ni les effets modernes.
6. Reprendre des screenshots desktop + mobile après intégration ; vérifier focus clavier sur login, nav, submit, boutons d’action.

## À éviter

- Pas de framework CSS lourd.
- Pas d’image générée contenant du texte.
- Pas de surcharge “aquarium” : maximum un fond de courant discret et un mark fort.
- Pas de couleurs statut uniquement par teinte : ajouter badges/libellés.
