# Changelog

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
