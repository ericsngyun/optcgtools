# Publishing under `ericsngyun`

The standalone intended remote is:

```text
https://github.com/ericsngyun/optcg-cards-css
```

The complete working project is currently published on the `holo-lab` branch of `ericsngyun/optcgtools` so it can be cloned immediately without changing that repository's `main` branch.

```bash
git clone --branch holo-lab --recurse-submodules https://github.com/ericsngyun/optcgtools.git optcg-cards-css
```

From a machine with GitHub CLI authenticated as `ericsngyun`, the branch can later be promoted into its own repository:

```bash
./scripts/publish-new-repo.sh
```

The project is GPL-3.0 because it is a derivative lab built from the GPL-3.0 upstream architecture.
