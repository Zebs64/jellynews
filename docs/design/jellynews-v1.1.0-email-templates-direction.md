# JellyNews v1.1.0 — Direction Aï pour templates newsletter

Statut : handoff design exploitable pour Motoko
Portée : nouveaux templates email v1.1.0, sans remplacer le template actuel
Outil choisi : direction textuelle + tokens email-safe. Pas d'image-gen, pas d'asset externe obligatoire, pas de CSS externe.

## Décision principale

Le template actuel `app/templates/email/newsletter.html` reste disponible comme `Classique` et reste le défaut.

Raison : il est déjà robuste pour l'email : tables `role="presentation"`, CSS inline, largeur 600 px, logo et affiches compatibles `cid:`, fallback poster textuel, dégradation Outlook acceptable. Les nouveaux templates doivent donc varier la hiérarchie et le rythme, pas introduire une usine à gaz.

## Données disponibles à respecter

Les directions ci-dessous restent compatibles avec le contexte actuel produit par `app/services/newsletter.py` :

- `title`
- `period_label`
- `preheader`
- `intro`
- `sections[]`
- `section.label`
- `section.entries[]`
- `item.name`
- `item.year`
- `item.badge`
- `item.overview`
- `item.url`
- `item.poster_src`
- `logo_src`
- `unsubscribe_url`
- `now_year`

Pour l'éditeur v1.1.0 par blocs, chaque direction est pensée comme une composition de blocs activables/déplaçables : preheader, header, intro, section header, media item, footer. Les blocs peuvent partager les mêmes variables et ne demandent pas de JS.

## Palette source JellyNews / Media Current

| Token email | Hex | Usage |
|---|---:|---|
| `jn-bg-deep` | `#07111f` | fond email principal |
| `jn-bg` | `#0b1626` | arrière-plan de zones larges |
| `jn-surface` | `#101c2d` | cartes média |
| `jn-surface-raised` | `#162336` | intro / blocs secondaires |
| `jn-border` | `#20344a` | bordures sobres |
| `jn-text` | `#f2f7fb` | texte principal |
| `jn-muted` | `#9fb0c3` | méta, aide, synopsis secondaire |
| `jn-muted-soft` | `#8b98a5` | dates / footer |
| `jn-cyan` | `#00f5d4` | accent rare, courant / focus visuel |
| `jn-blue` | `#00a4dc` | titres de section, liens |
| `jn-violet` | `#7c4dff` | profondeur / template plus éditorial |
| `jn-gold` | `#ffe66d` | mise en avant, top pick |
| `jn-danger` | `#ff6b7a` | erreurs éventuelles, à éviter dans les contenus normaux |

Typographie email : `font-family:'Segoe UI', Helvetica, Arial, sans-serif;` partout. Pas de webfont.

## Template 0 — Classique / défaut

Nom UI : `Classique`

Intention : newsletter sobre et fiable, proche du template existant. C'est la version de référence pour les administrateurs qui veulent un rendu prévisible.

Structure :

1. preheader invisible ;
2. conteneur 600 px ;
3. header centré avec logo optionnel, titre, période ;
4. intro IA en carte pleine largeur ;
5. sections par type de média ;
6. item média en carte horizontale : poster 110 px gauche, texte droite ;
7. footer avec désinscription.

Palette : conserver la palette actuelle : fond `#07111f`, cartes `#101c2d`, intro `#162336`, bordure `#20344a`, accent section `#00a4dc`.

Contraintes email : garder les tables et CSS inline existants ; ne pas ajouter de gradient critique ; ne pas ajouter d'asset décoratif.

Fallback sans poster : bloc 110 × 160 en `#20344a`, texte `Pas d'affiche`. C'est lisible mais minimal.

Mode compact : possible en réduisant le padding des cartes à 10–12 px et le synopsis à 1 ou 2 phrases côté données. Ne pas descendre le poster sous 82 px si l'affiche reste affichée.

## Template 1 — Courant éditorial

Nom UI : `Courant éditorial`

Intention : le template “magazine Jellyfin”. Il donne plus de présence au premier média de chaque section, puis liste les suivants plus sobrement. Idéal quand la semaine contient peu à moyennement de nouveautés et que l'administrateur veut un rendu plus premium.

Structure recommandée :

1. preheader invisible ;
2. header en bloc éditorial : logo optionnel à gauche ou centré, titre fort, période en petite capsule ;
3. intro IA en encadré “note de programmation” ;
4. pour chaque section :
   - `section-header` avec libellé + trait accent cyan/bleu ;
   - premier item en `hero-card` pleine largeur ;
   - items suivants en `standard-card` horizontales plus compactes ;
5. footer sobre.

Hiérarchie visuelle :

- `h1` : 28 px, `#f2f7fb`, poids 800 ;
- période : 12 px, uppercase possible, `#9fb0c3`, bordure `#20344a` ;
- intro : 15 px, ligne 1.65, `#cfd9e2`, fond `#162336` ;
- section : 18 px, `#00f5d4` ou `#00a4dc`, avec mini séparateur ;
- hero titre : 20 px, `#f2f7fb` ;
- standard titre : 16 px.

Palette :

- fond : `#07111f` ;
- container interne optionnel : `#0b1626` ;
- hero card : `#162336` avec bordure `#2f80b7` ;
- standard card : `#101c2d` avec bordure `#20344a` ;
- accent : `#00f5d4` pour le premier niveau, `#00a4dc` pour les liens ;
- highlight rare : `#ffe66d` pour un badge “À ne pas manquer” si le bloc éditeur en crée un plus tard.

Blocs recommandés :

- `preheader` obligatoire ;
- `header` obligatoire ;
- `intro` optionnel mais recommandé ;
- `section-header` obligatoire ;
- `hero-media-item` automatique sur le premier `section.entries[0]` ;
- `media-item` pour les suivants ;
- `footer` obligatoire.

Contraintes email :

- utiliser des tables imbriquées, pas de `display:flex` ;
- ne pas dépendre d'un vrai gradient CSS pour le hero ; préférer fond uni + bordure accent ;
- Outlook peut perdre les arrondis : le rendu doit rester propre carré ;
- éviter de mettre deux colonnes de texte dans le hero : poster gauche, contenu droite seulement.

Fallback sans poster :

- hero : bloc 150 × 220, fond `#20344a`, avec symbole texte très court `Media` ou `Pas d'affiche` ;
- standard : même fallback que Classique, mais garder un fond légèrement plus clair `#1b2d46` pour éviter une masse noire.

Mode compact :

- si une section dépasse 8 items, hero seulement pour la première section ou désactiver `hero-media-item` ;
- items suivants : poster 72–82 px, titre + badge + année, synopsis masqué ou limité à 120 caractères côté rendu ;
- padding vertical 10 px ;
- ne pas alterner gauche/droite : l'email mobile et Outlook souffrent, garder une lecture verticale prévisible.

## Template 2 — Catalogue compact

Nom UI : `Catalogue compact`

Intention : version dense pour semaines chargées, bibliothèques très actives ou emails avec beaucoup de médias. Elle assume la lisibilité et le poids avant l'effet “wow”. C'est le template recommandé quand le nombre de médias est élevé ou quand les posters intégrés risquent d'alourdir l'email.

Structure recommandée :

1. preheader invisible ;
2. header réduit : logo optionnel 120–140 px max, titre 24 px, période ;
3. intro IA optionnelle, moins haute ;
4. résumé en mini-compteurs textuels si Motoko expose plus tard les totaux par section ; sinon ne pas bloquer ;
5. sections ;
6. items en lignes compactes : petit poster 64–72 px ou aucun poster selon réglage ;
7. footer.

Hiérarchie visuelle :

- header plus petit que Classique ;
- titres de section en pills textuelles : `🎬 Films`, `📺 Séries`, `🎵 Musique`, 14–15 px ;
- item : titre 15 px, année muted, badge 11–12 px ;
- synopsis : 12–13 px, ligne 1.45, optionnel en compact strict.

Palette :

- fond : `#07111f` ;
- item rows : `#0b1626` ou `#101c2d` ;
- séparateurs : `#20344a` ;
- accent : `#00a4dc` seulement pour sections et liens ;
- éviter `#00f5d4` en masse : trop lumineux quand il y a 30 lignes.

Blocs recommandés :

- `preheader` obligatoire ;
- `header-compact` obligatoire ;
- `intro-compact` optionnel ;
- `section-header-pill` obligatoire ;
- `media-row-compact` obligatoire ;
- `footer` obligatoire.

Contraintes email :

- lignes sous forme de tables 100 % avec cellule poster fixe et cellule texte fluide ;
- largeur poster 64 ou 72 px, pas plus ;
- pas de mosaïque multi-colonnes : trop fragile dans Outlook/Gmail mobile ;
- pas de fond décoratif ;
- si posters intégrés, conseiller de limiter les images par option ou seuil pour préserver le poids.

Fallback sans poster :

- en mode compact, le fallback peut être une cellule 64 × 88 avec fond `#20344a`, ou une pastille de type (`Film`, `Série`, `Album`) si Motoko ajoute une valeur dérivée ;
- si aucun poster pour beaucoup d'items, autoriser `posterless compact` : supprimer la cellule poster et aligner le texte pleine largeur avec une bordure gauche `#20344a`.

Mode compact :

- ce template est le mode compact principal ;
- recommandation seuil : au-delà de 20 médias, masquer les synopsis par défaut dans la version email envoyée et les garder dans la preview/archive si souhaité ;
- au-delà de 50 médias ou du plafond `MAX_EMBEDDED_POSTERS`, afficher les posters restants par lien ou passer les items sans poster afin d'éviter un email trop lourd.

## Template 3 — Affiche de séance

Nom UI : `Affiche de séance`

Intention : version plus scénique, pensée comme une programmation de cinéma maison. Elle garde la robustesse email mais utilise un cadre sombre, un header plus dramatique et des blocs média qui ressemblent à des fiches de séance. À utiliser quand le nombre de médias est faible ou moyen.

Structure recommandée :

1. preheader invisible ;
2. header “marquee” : titre centré, période, petit séparateur cyan/violet en table ;
3. intro IA en bloc citation ;
4. sections avec libellé large ;
5. item média en carte verticale-hybride : poster plus présent 128–140 px à gauche, infos à droite ;
6. footer.

Hiérarchie visuelle :

- header : titre 30 px max, letter-spacing léger négatif si client le respecte ;
- période : 13 px `#9fb0c3` ;
- séparateur : table 100 %, hauteur 2 px, couleur unie `#00a4dc` ou deux cellules `#7c4dff` / `#00f5d4` ;
- titre item : 18 px ;
- badge : capsule textuelle `#00f5d4` sur fond `#07111f`, bordure `#20344a`.

Palette :

- fond principal : `#07111f` ;
- cadre : `#0b1626` ;
- carte : `#162336` ;
- bordure chaude : `#2f80b7` ;
- accent séance : `#7c4dff` + `#00a4dc`, cyan en point lumineux ;
- texte : `#f2f7fb`, synopsis `#9fb0c3`.

Blocs recommandés :

- `preheader` obligatoire ;
- `header-marquee` obligatoire ;
- `intro-quote` optionnel ;
- `section-header-marquee` obligatoire ;
- `media-card-feature` obligatoire ;
- `footer` obligatoire.

Contraintes email :

- pas de texte en image ;
- pas de vraie animation de marquee ;
- pas de background SVG ;
- séparateurs faits en tables/cellules colorées ;
- rester sur 600 px, poster 128–140 px max pour ne pas écraser le texte.

Fallback sans poster :

- bloc 128 × 188 avec fond `#20344a`, bordure `#2f80b7`, texte centré `Pas d'affiche` ;
- si le titre est long, ne pas augmenter la hauteur du fallback : laisser le texte droite prendre la place.

Mode compact :

- si plus de 12 médias, basculer automatiquement les items après le 12e en `media-row-compact` ou recommander `Catalogue compact` ;
- ne pas envoyer ce template avec 30 posters : il devient lourd et perd sa promesse éditoriale.

## Guidance blocs pour l'éditeur v1.1.0

Blocs communs à implémenter :

1. `preheader` : toujours présent, invisible, alimenté par `preheader`.
2. `header` : variantes `classic`, `editorial`, `compact`, `marquee`; paramètres : alignement, largeur logo, taille titre.
3. `intro` : variantes `card`, `compact`, `quote`; option désactivable si `intro` vide.
4. `section-header` : variantes `plain`, `divider`, `pill`, `marquee`.
5. `media-item` : variantes `classic-card`, `hero-card`, `compact-row`, `feature-card`.
6. `poster-fallback` : sous-bloc commun pour éviter trois implémentations divergentes.
7. `footer` : commun, avec `unsubscribe_url`.

Règles de déplacement :

- `preheader` doit rester avant le wrapper principal.
- `footer` doit rester dernier.
- `section-header` doit rester attaché à sa section.
- `media-item` peut changer de variante selon index/volume, mais ne doit pas sortir de sa section.
- `intro` peut être placé avant ou après le header, mais je recommande après le header pour continuité avec Classique.

## Règles email-safe à imposer

- CSS inline sur chaque élément critique.
- Tables `role="presentation"`, `cellpadding="0"`, `cellspacing="0"`, `border="0"`.
- Largeur conteneur : 600 px max.
- Pas de JS.
- Pas de CSS externe.
- Pas de webfont.
- Pas de `position`, `flex`, `grid`, `background-image` indispensable ou animation.
- Images : `display:block`, `border:0`, largeur explicite.
- Le contenu doit rester lisible sans images : alt utile + fallback poster.
- Les arrondis sont décoratifs seulement : Outlook Windows peut les ignorer.
- Les couleurs statut/importance ne doivent pas être le seul signal si un état fonctionnel est ajouté.
- Conserver `List-Unsubscribe` côté mailer et le lien footer quand disponible.

## Recommandation mode compact global

Seuils conseillés :

- 0–12 médias : `Classique`, `Courant éditorial` ou `Affiche de séance`.
- 13–20 médias : `Classique` ou `Catalogue compact`; hero limité à un seul item si `Courant éditorial` est utilisé.
- 21+ médias : `Catalogue compact` recommandé.
- 50+ posters intégrés : respecter `MAX_EMBEDDED_POSTERS`; prévenir dans l'UI que les affiches restantes passent en lien ou fallback.

En compact :

- poster 64–82 px ;
- synopsis optionnel ou tronqué court ;
- badge et année conservés ;
- padding réduit ;
- pas de mise en page multi-colonnes ;
- section headers plus sobres.

## Conseils UI admin pour miniatures / preview

Dans l'interface admin, ajouter un sélecteur de template qui ne surcharge pas l'écran `Apparence` :

1. cartes miniatures 160 × 110 ou 180 × 120, fond sombre, sans iframe obligatoire ;
2. chaque miniature doit montrer la silhouette du template, pas le contenu réel complet ;
3. libellé visible : `Classique`, `Courant éditorial`, `Catalogue compact`, `Affiche de séance` ;
4. badge `Défaut` sur `Classique` ;
5. badge `Recommandé volume élevé` sur `Catalogue compact` ;
6. action `Prévisualiser avec les dernières nouveautés` avant envoi ;
7. affichage d'un avertissement si le template choisi est peu adapté au volume détecté ;
8. option `Mode compact automatique au-delà de N médias` avec N par défaut à 20 ;
9. ne pas faire dépendre la sélection de miniatures raster : les miniatures peuvent être de petits blocs HTML/CSS dans le dashboard ;
10. pour les archives, stocker le HTML rendu comme aujourd'hui afin que le rendu historique ne change pas si le template évolue.

Miniatures suggérées :

- `Classique` : header centré + deux cartes horizontales.
- `Courant éditorial` : un gros hero + deux lignes compactes.
- `Catalogue compact` : trois lignes denses avec petit poster.
- `Affiche de séance` : header dramatique + grande carte feature.

## Handoff Motoko — intégration KISS

1. Garder `newsletter.html` comme source du template `classic` ou le dupliquer en `classic.html` sans changer le rendu par défaut.
2. Ajouter une abstraction de sélection côté rendu seulement après avoir un réglage persistant explicite, par exemple `newsletter_template` avec défaut `classic`.
3. Créer les nouveaux fichiers templates en Jinja2 sous `app/templates/email/`, un fichier par variante, plutôt qu'un méga-template rempli de conditions.
4. Factoriser seulement les constantes Python simples : noms de templates autorisés, valeur par défaut, seuil compact. Éviter un moteur de layout custom.
5. Réutiliser les mêmes variables de contexte au départ. Si un compteur par section est souhaité, il peut être dérivé dans le template via `section.entries|length`.
6. Pour les blocs déplaçables, commencer par une liste contrôlée de blocs connus par template. Ne pas exposer du HTML libre.
7. Ajouter des tests qui vérifient : `classic` reste défaut, chaque template rend sans erreur, pas de `<script>`, pas de CSS externe, présence du lien de désinscription quand demandé, fallback sans poster.

## Assets

Aucun nouvel asset nécessaire pour cette livraison. Les templates peuvent réutiliser le logo utilisateur `logo_src` et les posters existants. Les assets JellyNews actuels restent web/admin, pas indispensables à l'email.

Si Motoko veut enrichir plus tard : préférer mini séparateurs en HTML inline plutôt qu'un décor SVG dans l'email.

## Limites annoncées

Cette note n'est pas une maquette pixel-perfect : c'est une direction intégrable. Je n'ai pas remplacé le template actuel et je n'ai pas ajouté de prototypes HTML afin d'éviter de figer une implémentation avant la structure v1.1.0 de Motoko.

La validation finale devra être faite sur rendus réels Gmail/Outlook ou, au minimum, sur previews HTML envoyées en email de test. Mon QA ici couvre la cohérence avec le template actuel et les contraintes email-safe, pas le rendu des clients mail propriétaires.
