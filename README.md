# 🪼 JellyNews

Gestionnaire de newsletter automatisé pour serveur **Jellyfin**, conteneurisé avec Docker.
Chaque semaine, l'application interroge l'API Jellyfin, récupère les nouveautés
(films, séries — avec regroupement des nouveaux épisodes par série — et musique),
génère une introduction humoristique via un LLM (OpenRouter/OpenAI), et envoie
une newsletter HTML sombre inspirée du thème **ElegantFin** à vos abonnés —
avec en option un résumé sur Discord.

Fonctionnalités notables :

- **Affiches incorporées à l'email** (mode par défaut) : pas besoin d'exposer
  Jellyfin sur Internet ; ou mode « lien » pour des emails plus légers.
- **Désinscription en un clic** : lien signé par abonné + header
  `List-Unsubscribe` RFC 8058 (bouton natif Gmail/Outlook). Nécessite de
  renseigner l'URL publique de JellyNews dans l'onglet Apparence.
- **Filtrage par bibliothèque** : cochez les bibliothèques Jellyfin à inclure.
- **Titres et affiches cliquables** : deep links vers la fiche Jellyfin.
- **Archives** : chaque newsletter envoyée est consultable depuis l'admin.
- **Test LLM** dans l'interface (affiche l'erreur réelle de l'API).
- **Anti-brute-force** sur le login (5 essais / 15 min par IP).
- **Import/export** : abonnés en CSV, configuration en JSON.

## Arborescence

```
jellynews/
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── README.md
├── data/                        # Volume persistant (créé au 1er lancement)
│   ├── jellynews.db             #   - configuration, abonnés, logs (SQLite)
│   ├── secret.key               #   - clé de signature des sessions
│   └── uploads/logo.*           #   - logo personnalisé
└── app/
    ├── main.py                  # FastAPI : pages setup/login/dashboard
    ├── database.py              # SQLite : settings, users, abonnés, logs
    ├── auth.py                  # bcrypt + cookies signés (itsdangerous)
    ├── scheduler.py             # APScheduler : cron hebdomadaire configurable
    ├── routers/api.py           # API d'administration (authentifiée)
    ├── services/
    │   ├── jellyfin.py          # Récupération des ajouts récents
    │   ├── llm.py               # Intro humoristique (API compatible OpenAI)
    │   ├── mailer.py            # SMTP + logo inline (cid:)
    │   ├── discord.py           # Webhook Discord (embeds)
    │   └── newsletter.py        # Orchestration + rendu Jinja2
    ├── templates/
    │   ├── email/newsletter.html  # Template email (CSS 100 % inliné)
    │   └── web/                   # Interface d'administration
    └── static/                    # CSS + JS du portail
```

## Démarrage

```bash
docker compose up -d --build
```

Puis ouvrez **http://localhost:8050** :

1. **First-time setup** : créez le compte administrateur (mot de passe haché en bcrypt).
2. **Jellyfin** : URL interne (ex. `http://jellyfin:8096`), clé API
   (Tableau de bord Jellyfin → Clés API), et **URL publique** — indispensable
   pour que les affiches s'affichent dans les emails des abonnés.
3. **SMTP** : hôte, port, sécurité (STARTTLS/SSL), identifiants, expéditeur.
   Testez avec le bouton « Email de test ».
4. **IA / LLM** : clé API OpenRouter ou OpenAI + prompt humoristique.
   En cas d'échec du LLM, un texte de repli est utilisé (l'envoi n'est jamais bloqué).
5. **Planification** : jour + heure de l'envoi hebdomadaire (fuseau = `TZ` du compose).
6. **Discord** : URL de webhook (optionnel).
7. **Apparence** : titre + upload du logo (embarqué dans l'email en pièce jointe inline).
8. **Abonnés** : ajoutez les adresses, puis « Prévisualiser » ou « Envoyer maintenant ».

## Notes de sécurité & compatibilité

- **Sessions** : cookie HttpOnly + SameSite=Lax, signé avec une clé persistée
  dans le volume. Derrière un reverse-proxy HTTPS, ajoutez `COOKIE_SECURE=1`
  dans l'environnement du conteneur.
- **CORS** : aucun middleware CORS — le front et l'API partagent la même
  origine, c'est la configuration la plus sûre.
- **Secrets SMTP/LLM** : stockés dans SQLite (le serveur doit pouvoir les
  relire pour se connecter). Protégez le dossier `./data` en conséquence.
- **Template email** : tables HTML + CSS inliné uniquement (Gmail/Outlook ne
  supportent ni flexbox ni les feuilles de style externes) ; logo en `cid:`
  pour ne pas être bloqué comme image distante ; les posters restent des URLs
  pointant vers votre Jellyfin public.
- **Personnalisation du template** : décommentez le montage du dossier
  `templates/email` dans `docker-compose.yml` pour l'éditer sans rebuild.
