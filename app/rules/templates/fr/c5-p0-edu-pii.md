---
id: c5-p0-edu-pii
name: Confidentialité des élèves (ne pas toucher aux PII)
category: c5
priority: p0
layer: hard
trigger_default: hard-hook
tags: education; privacy
keywords: élèves ; confidentialité ; éducation
description: anonymisation PII + minimisation + conformité
donts: |
  - NEVER conserver dans la sortie/les produits intermédiaires le nom, le numéro d'élève, les informations familiales, l'adresse, les coordonnées et autres données identifiables
  - NEVER exporter au passage l'intégralité du dossier d'un élève
  - NEVER envoyer des données d'élèves vers un service en ligne externe
source: built-in
from: edu-pii
---

En travaillant sur des données éducation/élèves, respecter :

Discipline PII (données à caractère personnel) :
- NEVER conserver dans la sortie/les produits intermédiaires le nom, le numéro d'élève, les informations familiales, l'adresse, les coordonnées et autres données identifiables.
- Anonymiser avant traitement : remplacer les champs d'identité par un code/un placeholder ; l'analyse ne garde que les champs nécessaires.

Principe de minimisation :
- Prendre seulement les champs indispensables à la tâche ; NEVER exporter au passage l'intégralité du dossier d'un élève.
- Les notes/comportements s'affichent « en agrégat » (répartition de la classe) par priorité, pour éviter l'identification individuelle.

Conformité :
- Suivre le RGPD et le Code de l'éducation (dossier scolaire), ainsi que les recommandations de la CNIL ; un champ incertain ne se traite pas par défaut.
- Les données restent sur la machine ; NEVER envoyer des données d'élèves vers un service en ligne externe.

Discipline :
- Si des PII s'infiltraient dans les données, s'arrêter, anonymiser, puis continuer.
- Ce modèle ne constitue pas un avis juridique ; pour la conformité, consulter la juridique/le délégué à la protection des données de l'établissement.
