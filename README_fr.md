# Experientia · la colle entre vous et vos agents

**L'agent change. Votre expérience, non.**

[English](README.md) | [简体中文](README_zh.md) | [繁體中文](README_zh-TW.md) | [日本語](README_ja.md) | [한국어](README_ko.md) | [Deutsch](README_de.md) | **Français** | [Español](README_es.md) | [Русский](README_ru.md) | [Português (BR)](README_pt-BR.md)

---

Une petite scène qui revient chaque semaine.

Vous demandez à un agent de corriger une fonction d'export. Il code le fuseau horaire en dur sur UTC+8. Vous dites non, il faut suivre le fuseau du système. Il corrige, vous vérifiez, terminé.

Une semaine plus tard, même tâche, de nouveau UTC+8.

Vous commencez à vous demander si vous avez mal expliqué. Non. Vous avez très bien expliqué, dans une autre session. À l'instant où cette session se ferme, l'explication n'a jamais existé.

Puis vous changez d'outil. Ce que vous aviez appris à Claude Code, il faut le réapprendre à Codex, puis à Cursor. Six mois de « voilà comment ce genre de travail se fait » éparpillés dans quatre historiques de conversation, et rien ne vous suit.

Le secteur appelle ça le context engineering, ou la couche mémoire. Le nom est abstrait, le problème est simple. Comment faire pour qu'un agent se souvienne de vous.

Notre réponse va un cran plus loin. Se souvenir, c'est la ligne de départ. Progresser dans votre travail à chaque utilisation, voilà l'objectif.

Experientia ne fait donc qu'une chose. Il s'installe entre vous et l'agent, garde les parties de chaque collaboration qui ont vraiment compté, les vérifie, les distille en méthodes et en modes d'échec, puis les remet sur la table avant la tâche suivante. L'agent peut changer, il reste là. C'est ce que nous appelons la colle.

> *experientia est magistra*, l'expérience est la meilleure des maîtresses.

## Sur quoi le secteur parie, et ce qu'il rate

L'argent investi dans ce domaine en 2026 n'est pas inférieur à celui investi dans les modèles.

Le rapport 2026 Agentic Coding Trends d'Anthropic donne des chiffres. Les équipes qui entretiennent bien leurs fichiers de contexte terminent leurs tâches 55 % plus vite et font 40 % d'erreurs en moins. L'écart ne vient pas de la formulation, mais du fait de traiter « ce que le modèle voit » comme un problème d'ingénierie.

Le second axe, ce sont les skills. Anthropic a lancé Agent Skills en octobre 2025, publié le format comme standard ouvert le 18 décembre 2025, et à la mi-2026 une quarantaine d'agents lisent le même SKILL.md. C'est important. Pour la première fois, le savoir procédural peut voyager d'un outil à l'autre.

Puis SkillsBench a refroidi tout le monde. Le benchmark est paru en février 2026 (arXiv:2602.12670), 86 tâches, 11 domaines, 7 combinaisons agent et modèle, 7 308 trajectoires. Les skills curatés à la main font gagner 16,2 points de taux de réussite en moyenne. Les skills que les modèles s'écrivent eux-mêmes n'apportent rien en moyenne, et 16 tâches sur 84 se dégradent.

Un modèle ne sait pas écrire l'expérience dont il a besoin.

C'est exactement le trou que le secteur contourne sans pouvoir l'éviter. Le contenant existe. Le stockage existe. Personne ne fait le contrôle qualité.

| Camp | Exemples | Ce qu'il fait | Ce qu'il laisse de côté |
|------|----------|---------------|-------------------------|
| **Couches mémoire** | Mem0, Zep, Letta, Cognee | Stockent des **faits** dans des vecteurs, des graphes temporels ou un contexte étagé, puis les rappellent | Ne produisent pas de **méthodes**. Les données sont chez eux, pas sur votre disque |
| **Distillation de skills** | colleague.skill, nuwa-skill, dojo.md | Une seule fois. On donne la matière, on obtient un SKILL.md statique | Aucun retour d'expérience à l'exécution. Le skill ne se révise jamais selon ce qui vous a servi |
| **Harnais auto-évolutifs** | Hermes Agent (Nous Research), DeepSeek Harness | Le framework apprend, transforme les tâches terminées en SKILL.md et les affine | Les skills vivent dans le harnais et meurent avec lui. La création suit l'activité, pas la qualité, et les échecs ne sont pas comptés avant de devenir définitifs |
| **Évaluation de skills** | waza (Microsoft), dojo/limitless | Testent et filtrent les skills existants, comme du code en CI | Ne produisent pas de skills. Des outils pour auteurs de skills, pas un produit pour ceux qui travaillent |

Chaque camp résout un tronçon. Personne ne relie les tronçons.

**Ce lien, c'est Experientia.** Capturer, vérifier, distiller, injecter, réviser. Une boucle fermée. En octobre 2026, nous n'avons pas trouvé de produit ouvert qui remplisse les quatre conditions à la fois.

- **Capture automatique.** Pas d'export de transcript. Les données entrent pendant que vous travaillez
- **Un filtre de vérification.** Rien d'improbé n'est injecté. Un échec doit se répéter avant de devenir un savoir permanent
- **Local et portable.** Chaque actif est un simple fichier sur votre machine. Ni compte, ni cloud, ni base vectorielle
- **Révision continue.** Les actifs sont des documents vivants qui fusionnent, se déprécient et raccourcissent. Ils ne s'empilent pas

## Mémoire n'est pas expérience

Cette distinction porte tout le reste.

La mémoire stocke des faits. La personne préfère TypeScript. Les dépendances passent par uv. Mercredi dernier, on touchait à l'export. Tout cela s'indexe, s'embedde, se met dans un graphe.

L'expérience est un jugement. Les migrations de ce type touchent les tests avant l'implémentation, parce que la dernière fois nous sommes allés droit dans l'implémentation et avons cassé trois avals. Cela ne se récupère pas par recherche. Cela doit pousser à partir de ce qui a réellement eu lieu, et quelqu'un doit confirmer que c'était juste.

| | Mémoire | Expérience |
|---|---|---|
| Contient | Faits, préférences, état | Méthodes, modes d'échec, critères |
| Vient de | Ce qui a été dit | Ce qui a été fait, et où ça a cassé |
| Récupérable | Oui | Non. Seulement vérifiable et révisable |
| Expire par | Écrasement | Dépréciation, fusion, réduction |
| Après un changement d'outil | Dépend de la plateforme | Un fichier dans votre main, il suit |

Les produits de mémoire sont bons dans leur domaine. Mem0 part du vectoriel, Zep modélise les faits dans le temps sous forme de graphe, Letta pagine le contexte comme un système d'exploitation pagine sa mémoire. Mais ils résolvent le fait de se souvenir, pas celui d'apprendre. Une collection complète de faits ne rend pas meilleur au travail.

Nous ne construisons pas un classeur plus complet. Nous construisons un collègue expérimenté qui change d'avis quand les preuves changent.

## Comment ça tourne

```
Vous travaillez ──> l'agent collabore (enregistré automatiquement)
   ^                                |
   |                                v
plus vite, mieux  <──  injection  <──  distillation (filtrée)
```

**Capturer.** Vous travaillez normalement. Les fichiers de session sont déjà sur le disque, rien à exporter, rien à coller. Les agents installés sont détectés automatiquement, zéro configuration.

**Vérifier.** Chaque expérience porte un signal de confiance G, issu de trois sources, votre confirmation explicite, des signaux déterministes dans la session, et l'auto-évaluation binaire du modèle. Tout ce qui est sous le seuil n'est jamais injecté. Un mode d'échec doit se répéter avant de devenir permanent. C'est la réponse d'ingénierie à SkillsBench. Seule l'expérience vérifiée mérite de composer.

**Distiller.** Le travail récurrent devient une méthode paramétrée. Les erreurs récurrentes deviennent des modes d'échec de premier ordre. Vos corrections et refus deviennent des préférences.

**Injecter.** Avant chaque requête, le proxy la réécrit avec les actifs pertinents dans un budget fixe (800 tokens par défaut), dans un format stable qui préserve le cache de prompt. Vous voyez exactement ce que le modèle verra, vous pouvez éditer ou désactiver chaque entrée, ou demander au modèle connecté de la réécrire. Les longues sessions ne diluent pas vos règles, les contraintes dures sont réinjectées au niveau du proxy, la 30e manche compte autant que la 1re.

**Réviser.** Les actifs sont des documents vivants. L'expérience nouvelle fusionne dans l'ancienne, les entrées périmées sont dépréciées, le document raccourcit. Une base de connaissances qui ne fait que croître est abandonnée en six mois.

Un tour produit cinq types d'actifs, physiquement deux formats de fichiers, `skills/<tronc>/<catégorie>.md` et `preferences/<tronc>.md`.

| Actif | Contenu | Ressenti à l'usage |
|-------|---------|--------------------|
| **Insights d'expérience** | Des leçons précises, ce qui marche et ce qui ne marche pas | « Il se souvient de ce que j'ai corrigé » |
| **Mes méthodes** | Le travail récurrent cristallisé en procédure paramétrée | « Il sait comment ce genre de tâche se fait » |
| **Modes d'échec** | Quels chemins cassent et pourquoi, de premier ordre | « Il ne me laisse pas retomber dans le même trou » |
| **Playbook vivant** | Le contexte injecté est un document curaté par incréments, fusionné et élagué | « Sa méthodologie monte en niveau au lieu de s'empiler » |
| **Mes préférences** | Vos critères, votre goût, vos arbitrages, induits de vos corrections | « Il connaît ma barre, je ne la réexplique plus » |

Deux vitesses, un seul volant. La vitesse quotidienne est le défaut, curation incrémentale pour le travail ouvert, aucun signal de réussite nécessaire. La vitesse renforcée est optionnelle, pour les tâches avec un score explicite (tests réussis, PnL de backtest), où un moteur RL ajuste directement les poids de stratégie.

## À quoi ressemble « mieux à chaque usage »

Première fois. Il suit un schéma générique. Vous surveillez chaque étape, prêt à corriger.

Dixième fois. Il sait que dans ce projet les tests précèdent l'implémentation. Il sait que vous refuserez « on fait marcher d'abord ». Il sait pourquoi vous avez abandonné la dernière approche.

Centème fois. Vous dites « comme la dernière fois » et il sait de laquelle il s'agit.

| | 1re fois | 10e fois | 100e fois |
|---|---|---|---|
| Ce que vous dites | Un paragraphe de contexte et de contraintes | Quelques jugements clés | Un repère |
| Comment il échoue | Dans des trous que vous connaissez déjà | Parfois dans un nouveau | Il connaît les trous et les contourne |
| Votre rôle | Main dans la main | Validation | Direction |

C'est aussi pourquoi changer d'agent ne le dérange pas. Vous changez l'exécutant, pas le critère. Le critère reste de votre côté.

## v1.1 : la mémoire descend d’un cran

v1.0 répondait à « est-ce qu’il retient ». v1.1 répond à « est-ce qu’il retient juste ».

Stocker plus n’est pas récupérer juste. Cette version travaille trois endroits qui restaient flous.

**Ce qui doit être oublié l’est vraiment.** Les entrées oubliées en douceur, celles écartées, celles remplacées par une version plus récente : aucun chemin de lecture par défaut ne les renvoie, y compris le canal MCP utilisé par les agents. La recherche les filtrait, mais récupérer une entrée par identifiant ne le faisait pas. Il restait une porte de service.

**Une autre formulation, même correspondance.** Vous demandez « comment on a réparé ce Module not found la dernière fois », l’entrée dit « réinstaller la dépendance » : pas un mot en commun. v1.1 extrait trois types de clés d’entité de chaque enregistrement — formulations d’erreur, squelettes de commande, noms de projet — et marque les correspondances. Le seuil ne bouge pas : aucune correspondance, aucun résultat.

**Il sait pourquoi il croit quelque chose.** Chaque expérience doit renvoyer à ce que vous avez réellement dit. Le verrou de preuve passe de « localiser la citation » à « le candidat entre dans la bibliothèque » : une citation de deux caractères inventée par le modèle passait parce que n’importe quel message la contient. Plus maintenant. À l’inverse, votre « là c’est bon » en validation compte toujours.

**Le mode dégradé dit la vérité.** Sans base d’index, le moteur retombe sur de simples fichiers. Oubli doux, remplacement et restauration renvoyaient un succès sans rien écrire. Désormais ils écrivent ou signalent l’échec.

Deux points d’ingénierie. Le chemin chaud de récupération ne re-tokenise plus le même texte ni ne redérive les clés d’entité : sur une bibliothèque de 3 000 entrées, la queue lente (95 % des requêtes) passe de 106 ms à 41,5 ms. `scripts/gate_report.py` sort en un passage l’inventaire des couches, le backtest du verrou et la latence de récupération.

## Démarrage rapide

1. Téléchargez la version de votre plateforme depuis [GitHub Releases](https://github.com/sabre232/experientia/releases), `experientia-windows-x64.zip`, `experientia-macos.dmg`, `experientia-linux-x64.tar.gz` (une arborescence onedir PyInstaller, non empaquetée en AppImage pour la v1.1). Décompressez et lancez `Experientia`. Les builds ne sont pas signés. Si Gatekeeper bloque sur macOS, faites un clic droit pour ouvrir une fois. Si SmartScreen apparaît sous Windows, cliquez sur « Informations complémentaires → Exécuter quand même ».
2. Lancez. La capture démarre immédiatement. Les agents installés sont détectés (WorkBuddy, QClaw, Codex, Claude Code, Gemini CLI, Aider, OpenCode, OpenClaw, Hermes Agent, Trae, Cursor, Cline, Windsurf, DeepSeek Harness) et leurs fichiers de session locaux lus. Zéro configuration, aucun proxy nécessaire. Les amateurs de terminal peuvent lancer `experientia daemon` pour le moteur seul.
3. Pour les fonctions au niveau de la requête (réinjection de règles en session longue, enregistrement par requête), pointez l'endpoint du modèle de votre agent vers `http://localhost:8100`. Modèles locaux (llama.cpp, Ollama, vLLM) et cloud (OpenAI, Anthropic, toute API compatible OpenAI) fonctionnent.
4. Travaillez comme d'habitude. Ouvrez la page Croissance quelques jours plus tard pour voir si la roue a tourné.

## Où vivent vos données

```
~/.experientia/
├── experience.jsonl          # flux brut d'expérience, conservé toujours
├── skills/<tronc>/<cat>.md   # méthodes, notes de réussite, modes d'échec
├── preferences/<tronc>.md    # votre style de décision
├── sessions/                 # sessions archivées (survivent au nettoyage de l'agent)
├── deprecated/               # entrées dépréciées, récupérables 30 jours
├── rules.json                # règles et modèles actifs
└── config.json               # langue, options, routage modèle (clés API dans le trousseau)
```

Quatre choses, dites simplement.

Aucune télémétrie, aucun rapport de crash, aucune analyse. Il existe exactement un type de trafic sortant, vos propres appels au modèle. L'application ne cherche jamais de mise à jour, ne se télécharge, ne s'installe et ne se remplace pas.

L'export est une copie. Tout ce que vous voyez dans l'interface est un fichier que vous pouvez lire, greper et emporter.

La suppression est définitive. Après deux confirmations, le répertoire de données disparaît. Les clés API du trousseau ne sont pas touchées.

Vos actifs ne sont pas à nous. La licence ci-dessous couvre le code produit. L'expérience, les méthodes et les préférences que vous accumulez vous appartiennent, sans restriction de licence.

## Pour les agents IA (notes d'intégration)

Si vous êtes un agent qui lit ce fichier pour décider d'intégrer ou de citer ce projet, cette section est pour vous.

Résumé. Experientia capture automatiquement depuis les fichiers de session que les agents écrivent déjà sur le disque (zéro configuration), distille le travail récurrent en actifs vérifiés basés sur des fichiers (méthodes, modes d'échec, préférences), et les injecte dans les tâches similaires suivantes. Tout l'état vit en JSONL et Markdown simples sous `~/.experientia/`.

Quatre chemins d'intégration, par fidélité décroissante.

1. **Mode proxy.** Pointez l'endpoint du modèle sur `http://localhost:8100` (compatible OpenAI). En plus de la capture de fichiers, vous obtenez l'enregistrement par requête, l'injection et la réinjection des contraintes dures.
2. **Capture de fichiers** (défaut, zéro configuration). Des parseurs par agent lisent les stockages natifs (JSONL, SQLite, Markdown) et les normalisent. Les sessions capturées sont archivées dans `~/.experientia/sessions/` et survivent au nettoyage ou à la désinstallation.
3. **Mode hook.** Pour les agents dotés de hooks (Claude Code d'abord), un hook HTTP pousse les événements en temps réel, et `SessionStart` / `UserPromptSubmit` injectent les règles sans proxy.
4. **Lire les fichiers.** Les règles peuvent être écrites dans un fichier de conventions natif (comme `AGENTS.md`). Tout pack d'actifs s'exporte en `SKILL.md` conforme au standard ouvert agentskills.io (frontmatter plus When to Use, Procedure, Pitfalls, Verification), chargeable par Hermes, OpenClaw, Claude Code et tout autre agent compatible. L'inverse fonctionne aussi.

Ce que ce n'est pas. Pas une base vectorielle, pas une API de mémoire, pas un service cloud, pas un outil de fine-tuning. Il ne touche pas aux poids du modèle. Tout se passe au niveau du contexte, ce qui explique que les modèles locaux et cloud se comportent pareil.

Les entrées injectées ont passé le filtre de confiance. Les blocs d'injection sont marqués dans le contexte et séparés des instructions utilisateur. Traitez-les comme un a priori curaté, pas comme un dogme.

## Développement et tests

Cette section est maintenue en version complète dans les versions anglaise et chinoise, pour éviter la dérive entre langues. Les détails sur les tests, le packaging et la signature sont dans [README.md](README.md).

## Licence

Le code est sous double licence. Choisissez celle qui correspond à votre usage.

**Usage personnel, interne à l'entreprise, ou recherche.** AGPLv3. Installez, utilisez. Personne à contacter, rien à payer.

**Usage commercial compatible avec le copyleft.** Toujours AGPLv3. Vendre, modifier, déployer : c'est permis. La condition a un périmètre précis : ce que vous modifiez, ou la partie que vous intégrez à un service que vous proposez, doit être publiée sous AGPLv3. Votre propre code produit n'est pas entraîné, à condition que les deux soient des œuvres distinctes communiquant via une frontière de processus ou une interface, et non un seul programme combiné.

**Vous ne pouvez pas ouvrir votre intégration, ou vous voulez bâtir un service concurrent.** BUSL-1.1, conditions commerciales par accord ; contactez le mainteneur. Sur cette voie, l'usage non commercial reste gratuit, et chaque version passe sous AGPLv3 quatre ans après sa publication. La restriction est limitée dans le temps, pas permanente.

**Vos données ne sont pas sous licence du tout.** Tout ce que vous accumulez ou exportez avec Experientia, des sessions brutes aux méthodes et préférences, vous appartient sans aucune condition. Usage commercial, closed-source, transfert à un tiers : rien de tout cela n'est restreint. La licence ne porte que sur le code de ce produit.

## Feuille de route

v1.1 est open source et gratuit. Pas de connexion, pas de compte, pas de paywall, pas de fonctionnalités d'équipe.

## Références

- Anthropic, 2026 Agentic Coding Trends Report. Source des chiffres 55 % et 40 % sur les fichiers de contexte entretenus
- SkillsBench, Benchmarking How Well Agent Skills Work Across Diverse Tasks, arXiv:2602.12670, février 2026
- Standard ouvert Agent Skills, agentskills.io, publié le 18 décembre 2025
- De l'expérience au skill est un axe de recherche actif, ExpeL, ACE (Agentic Context Engineering), Voyager, et l'apprentissage par renforcement à partir de l'expérience