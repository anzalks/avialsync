# Security policy

## Supported versions

Security fixes go into the latest release on PyPI and the installers built from the same tag.
Older releases are not patched; upgrade to the latest one.

## Reporting a vulnerability

Please report security problems privately, not in a public issue. Use GitHub's private reporting:
on the repository's **Security** tab, choose **Report a vulnerability**. If that option is not
available, open an issue that says only that you have a security report and asks for a private
contact, without any details.

Include what you found, the version (Help → About shows it), your operating system, and the steps
or file that trigger it. You will get an acknowledgement, and the fix will be credited to you in
`CHANGELOG.md` unless you would rather not be named.

## Scope

AvialSync is a desktop application that reads recordings from local disk and, when you ask it to,
from DANDI. The most relevant reports are files that make it execute code, write outside the
locations you chose, or read data it was not asked to read. Plugins are Python code you install
yourself and run with your own permissions; a plugin that does something harmful is not a
vulnerability in AvialSync.
