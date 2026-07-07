# Changelog

## v1.1.2 — Mascotte JellyNews sur l’accueil

- Mascotte JellyNews ajoutée au panneau d’accueil administrateur, positionnée en haut à droite du héros façon mockup fourni.
- Asset transparent `jellynews-mascot.png` embarqué dans les fichiers statiques de marque.
- Layout responsive ajusté : texte protégé sur desktop/tablette, mascotte replacée au-dessus du titre sur petit écran.
- Version applicative, cache-buster et client Jellyfin passés en `1.1.2`.

Documentation détaillée : `docs/releases/v1.1.2.md`.

## v1.1.1 — Diagnostic SMTP détaillé

- Diagnostic SMTP structuré ajouté : classe d’erreur, code SMTP, message neutralisé, catégorie, aide administrateur et caractère réessayable.
- Mappings opérationnels pour `550 5.7.1`, `554 5.7.1`, `552 5.3.4`, `451 4.7.0`, `421`, plus règles générales `4xx` temporaires et `5xx` permanentes.
- Historique admin enrichi avec affichage échappé/tronqué des diagnostics SMTP, sans HTML libre.
- `send_logs` migré avec colonnes SMTP idempotentes et export/import rétrocompatible avec les sauvegardes anciennes.
- Formulation corrigée : messages “acceptés par le serveur SMTP”, sans promesse de livraison inbox.
- Limites explicitement documentées : pas de bounce entrant/DSN, pas de preuve inbox et pas de retry automatique avancé.
- Version applicative, cache-buster et client Jellyfin passés en `1.1.1`.

Documentation détaillée : `docs/releases/v1.1.1.md`.

## v1.1.0 — Templates newsletter et éditeur contrôlé

- Template historique conservé comme `Classique` et défaut rétrocompatible.
- Nouveaux templates email-safe issus de la direction Aï v1.1.0 : `Courant éditorial`, `Catalogue compact` et `Affiche de séance`.
- Panneau Apparence / Newsletter étendu : sélection template, blocs contrôlés, activation/désactivation des blocs optionnels, réordonnancement ↑ ↓, reset et preview.
- Validation serveur stricte : registre de templates, blocs connus uniques, blocs obligatoires verrouillés, aucun HTML libre.
- Preview admin et email de test basculés sur le rendu newsletter réel, avec échantillon contrôlé si Jellyfin est indisponible.
- Export/import JSON complet enrichi avec `newsletter_template_id` et `newsletter_blocks_json`, rétrocompatible avec les sauvegardes legacy.
- Staging v1.1.0 validé avant documentation, avec revue Makise et verdict sécurité Futaba approuvés.
- Version applicative, cache-buster et client Jellyfin passés en `1.1.0`.

Documentation détaillée : `docs/releases/v1.1.0.md`.

## v1.0.4 — Accueil dashboard et navigation active

- Accueil admin ajouté comme panneau par défaut, avec bouton Accueil en tête de sidebar et raccourci via le logo JellyNews.
- Résumé opérationnel protégé par session admin : prochain envoi, nouveautés Jellyfin sur la période configurée, abonnés actifs et dernier envoi.
- Correction du bouton actif de sidebar : suppression du pseudo-élément vertical parasite sans retirer l'état actif ni le focus clavier visible.
- Assets web et client Jellyfin préparés en `1.0.4` pour cache-buster de release.

Documentation détaillée : `docs/releases/v1.0.4.md`.

## v1.0.3 — Cache-buster et throttling SMTP

- Version applicative centralisée en `1.0.3` et réutilisée par le client Jellyfin, l'export JSON et l'interface.
- Assets web versionnés avec `?v=1.0.3` pour éviter le hard refresh navigateur après release (`style.css`, `app.js` et SVG statiques concernés).
- Envoi newsletter maintenu en messages individuels : un seul destinataire en `To`, aucun `Cc/Bcc`, header `List-Unsubscribe` propre quand l'URL publique est configurée.
- Throttling SMTP configurable par taille de vague et pause entre vagues, avec validation de bornes.
- `/api/send-now` lance la campagne en arrière-plan et refuse un second lancement concurrent.
- Logs d'envoi enrichis : total destinataires, succès, échecs partiels masqués et statut synthétique.
- Documentation de délivrabilité ajoutée : SPF/DKIM/DMARC, réputation IP/domaine, quotas SMTP, désinscription et limites du verrou en mémoire.
- Rollback précisé : sauvegarder `data/`, restaurer l'image précédente et purger le cache proxy si nécessaire.

Documentation détaillée : `docs/releases/v1.0.3.md`.

## v1.0.2 — Sauvegarde complète et UI Media Current

- Export JSON `/api/settings/export` étendu : configuration, abonnés, historique des envois et archives de newsletters.
- Import JSON `/api/settings/import` compatible avec les anciens exports v1.0.1 settings-only.
- Import v1.0.2 fusionnel et idempotent autant que possible : emails normalisés/dédupliqués ; logs et archives dédupliqués sur les colonnes métier exportées.
- Erreurs d'import explicites en HTTP 400 pour JSON invalide, schéma non supporté, timezone invalide, email invalide ou historique mal formé.
- Refonte UI “Media Current” : thème sombre Jellyfin/media/newsletter, logo SVG, tables responsives, badges de statut et panneau Sauvegarde complète.
- Version du client Jellyfin passée à `1.0.2`.

Notes sécurité : le fichier de sauvegarde contient toujours les secrets de configuration nécessaires au fonctionnement (SMTP, Jellyfin, LLM). Il n'inclut pas les comptes admin, `secret.key`, la base SQLite brute ni les fichiers uploadés.

Rollback conseillé : sauvegarder le volume `data/` avant déploiement v1.0.2, puis restaurer ce volume avec l'image précédente en cas de retour arrière. Ne pas importer un export complet v1.0.2 dans v1.0.1 : l'ancien import ne connaît pas les sections abonnés, logs et archives.

Documentation détaillée : `docs/releases/v1.0.2.md`.
