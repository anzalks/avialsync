# Translation catalogues

Compiled `.qm` files go here and are loaded by `avialsync.ui.i18n` for the
user's locale, falling back silently to English when none matches.

To add a language:

    pyside6-lupdate $(git ls-files 'src/avialsync/**/*.py') -ts avialsync_<lang>.ts
    # translate the .ts, then
    pyside6-lrelease avialsync_<lang>.ts -qm avialsync_<lang>.qm

`avialsync.ui.i18n.translatable_ratio` reports how much of the interface is
currently wrapped for extraction. It is deliberately a measurement rather than
a claim: a partial wrap presents an application as translatable while half of
it stays English, which is worse than being plainly untranslated.
