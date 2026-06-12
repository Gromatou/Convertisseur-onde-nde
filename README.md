# Convertisseur ONDE ↔ NDE

[![Démo en ligne](https://img.shields.io/badge/démo-en_ligne-0ce6f2?style=for-the-badge&logo=githubpages)](https://Gromatou.github.io/Convertisseur-onde-nde/)

> **Convertisseur de fichiers ultrasonores** entre les formats **ONDE** (COFREND/EPRI v0.9.0) et **NDE** (Evident v4.2.0).  
> Conversion **100% locale** dans le navigateur — **aucune donnée envoyée à un serveur**.

---

## ✨ Fonctionnalités

- **Conversion bidirectionnelle** ONDE → NDE et NDE → ONDE
- **Support des références HDF5** (H5Rcreate / H5Rdereference) via module WASM dédié
- **Préservation des données brutes** (int16, float32, uint8 — aucun type converti)
- **Tableau de correspondance complet** des champs ONDE ↔ NDE avec recherche et filtrage
- **Interface sombre professionnelle** adaptée aux environnements de laboratoire
- **Génération de fichier test NDE** pour validation
- **Statistiques de conversion** (nombre de datasets, groupes, avertissements)
- **246 tests unitaires** validant le mapping et la détection de format

## 🚀 Utilisation

1. **Glisser-déposer** un fichier `.h5`, `.nde` ou `.onde` dans la zone prévue (ou cliquer pour parcourir)
2. Le format est **détecté automatiquement** et la direction de conversion est affichée
3. Cliquer sur **Convertir** — le fichier converti est prêt au téléchargement

## 📁 Formats supportés

| Extension | Format | Spécification | Dépôt |
|-----------|--------|---------------|-------|
| `.onde` | **ONDE** — Open Non Destructive Evaluation | COFREND/EPRI v0.9.0 | [github.com/COFREND/ONDE-format](https://github.com/COFREND/ONDE-format) |
| `.nde` | **NDE** — NDE Open File Format | Evident v4.2.0 | [github.com/Evident-Industrial/NDE_Open_File_Format](https://github.com/Evident-Industrial/NDE_Open_File_Format) — [ndeformat.com](https://ndeformat.com) |
| `.h5` | HDF5 | Conteneur générique (détection automatique ONDE ou NDE) | [hdfgroup.org](https://www.hdfgroup.org) |

### À propos des formats

- **ONDE** (Open Non-Destructive Evaluation) est une initiative conjointe de la [COFREND](https://www.cofrend.com/) et de l'[EPRI](https://www.epri.com/) visant à définir un format ouvert et standardisé pour les données de contrôle non destructif par ultrasons. Le format utilise HDF5 comme conteneur, avec des métadonnées stockées en attributs HDF5 et des références entre objets (`H5T_STD_REF_OBJ`). Version actuelle : v0.9.0 (mai 2026).

- **NDE** (NDE Open File Format) est le format ouvert développé par [Evident Scientific](https://www.evidentscientific.com/) (anciennement Olympus), déjà en production sur les appareils OmniScan X3/X4. Le format utilise HDF5 comme conteneur, avec des métadonnées stockées en JSON dans les datasets `/Properties` et `/Public/Setup`. Version actuelle : v4.2.0 (octobre 2025).

---

## 🛠️ Détails techniques

- **[h5wasm](https://github.com/usnistgov/h5wasm)** — bibliothèque HDF5 compilée en WebAssembly pour la lecture/écriture dans le navigateur
- **Module WASM custom** (`lib/h5wasm-ref.js` + `.wasm`) — fonctions de manipulation de références HDF5 (`H5Rcreate`, `H5Rdereference`, `H5Rget_name`) nécessaires au format ONDE, compilé avec **Emscripten** contre [libhdf5-wasm](https://github.com/usnistgov/libhdf5-wasm)
- **Conversion** : `src/mapping.js` (table de correspondance) + `src/converter.js` (moteur h5wasm)
- **Tests** : `tests/converter.test.js` — 246 tests unitaires
- **Interface** : HTML/CSS/JS vanilla — aucun framework, aucune dépendance serveur

---

## 📄 License

Domaine public ([The Unlicense](https://unlicense.org/)). Voir [`LICENSE`](LICENSE).

---

*Codé par IA (Deepseek V4 en mode agentique, coût total ~0,55 €).*
