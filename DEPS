# ChrobaltProject/DEPS
vars = {
    'chromium_git_url': 'https://chromium.googlesource.com',
    'chromium_version_tag': '114.0.5735.358',
    'chromium_src_dir': 'src',
}

deps = {
    Var('chromium_src_dir'): Var('chromium_git_url') + '/chromium/src.git@refs/tags/' + Var('chromium_version_tag'),
}

hooks = [
    {
        "name": "apply_cobalt_patches_m114",
        "pattern": ".",
        "action": ["python3", "cobalt/tools/apply_patches.py",
                   "--chromium-src-dir", Var('chromium_src_dir'),
                   "--patch-dir", "cobalt/patches/m114"],
    },
]

