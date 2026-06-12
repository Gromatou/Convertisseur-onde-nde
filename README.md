# Convertisseur ONDE ↔ NDE

[![Démo en ligne](https://img.shields.io/badge/démo-en_ligne-0ce6f2?style=for-the-badge&logo=githubpages)](https://Gromatou.github.io/Convertisseur-onde-nde/)

> **Convertisseur de fichiers ultrasonores** entre les formats **ONDE** (COFREND/EPRI v0.9.0) et **NDE** (Evident v4.2.0).  
> Conversion **100% locale** dans le navigateur — **aucune donnée envoyée à un serveur**.

---

## ✨ Fonctionnalités

- **Conversion bidirectionnelle** ONDE → NDE et NDE → ONDE
- **Support des références HDF5** (H5Rcreate / H5Rdereference) via module WASM dédié
- **Préservation des données brutes** (datasets, groupes, attributs)
- **Tableau de correspondance complet** des champs ONDE ↔ NDE avec recherche et filtrage
- **Interface sombre professionnelle** adaptée aux environnements de laboratoire
- **Génération de fichier test NDE** pour validation
- **Statistiques de conversion** (nombre de datasets, groupes, avertissements)

## 🚀 Utilisation

1. **Glisser-déposer** un fichier `.h5`, `.nde` ou `.onde` dans la zone prévue (ou cliquer pour parcourir)
2. Le format est **détecté automatiquement** et la direction de conversion est affichée
3. Cliquer sur **Convertir** — le fichier converti est prêt au téléchargement

## 📁 Formats supportés

| Extension | Format | Spécification |
|-----------|--------|---------------|
| `.onde` | ONDE | COFREND/EPRI v0.9.0 |
| `.nde` | NDE | Evident v4.2.0 |
| `.h5` | HDF5 | Conteneur générique (détection automatique ONDE ou NDE) |

## - **codé par IA** L'entièretée du code a été générée en utilisant Deepseek V4 en mode agentique, cout total : 55 centimes.
prompt : creer un convertisseur de fichiers ultrason, entre les formats ONDE et NDE, fait des recherches sur ces formats, telecharge les données par exemple le setup json shema pour nde et le ondefields, et creer une application web qui permet de convertir localement son fichier d'un format a l'autre dans les 2 sens. Fait des tests pour verifier qu'il n'y a pas d'erreur, délegue les taches pour economiser des ressources, prend ton temps pour faire des rechercehs complettes et etablir un tableau de correspondance complet

## 🛠️ Détails techniques

- **[h5wasm](https://github.com/usnistgov/h5wasm)** — bibliothèque HDF5 compilée en WebAssembly pour la lecture/écriture de fichiers HDF5 dans le navigateur
- **Module WASM custom** (`lib/h5wasm-ref.js` + `lib/h5wasm-ref.wasm`) — implémente les fonctions de manipulation de références HDF5 (`H5Rcreate`, `H5Rdereference`) nécessaires au format ONDE, compilé avec **Emscripten**
- **Interface** HTML/CSS/JS vanilla — aucun framework, aucune dépendance serveur
- **Stockage** — tout le traitement s'effectue dans la mémoire du navigateur ; le fichier converti est téléchargé via `Blob` / `URL.createObjectURL`

## 📄 License

Distribué sous licence MIT. Voir le fichier [`LICENSE`](LICENSE) pour plus d'informations.
