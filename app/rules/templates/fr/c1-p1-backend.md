---
id: c1-p1-backend
name: Ingénierie API backend
category: c1
priority: p1
layer: structure
trigger_default: always
tags: engineering; architecture
keywords: API ; backend ; interface
description: contrat d'abord + sémantique d'erreur + idempotence et limites
source: built-in
from: eng-backend
---

Développement backend/API — règles :

Contrat :
- Définir le schéma entrée/sortie de l'API avant d'écrire l'implémentation ; pour changer un contrat, changer d'abord la doc/les tests, puis le code.
- La nomenclature des champs exposés doit rester cohérente avec l'API existante ; NEVER plusieurs orthographes pour la même signification.

Erreurs et statuts :
- Utiliser les codes HTTP corrects (4xx erreur client, 5xx erreur serveur) ; le corps d'erreur porte un code lisible par machine + un message lisible par humain.
- NEVER avaler une exception et renvoyer un 200 vide ; soit traiter, soit propager.

Idempotence et limites :
- Les écritures (surtout celles qui touchent à l'argent) : prévoir une clé d'idempotence ; NEVER supposer qu'une requête n'arrive qu'une fois.
- Toujours valider les paramètres d'entrée (type/plage/longueur) ; NEVER faire confiance à l'appelant.

Journal :
- Noter « ce qui s'est passé + contexte clé » ; NEVER journaliser des secrets, des tokens, des champs sensibles du corps de requête.
