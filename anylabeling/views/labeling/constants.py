"""Constants shared by labeling view modules.

Only put constants here that several view modules need and that must not
create an import cycle (the labeling widget imports both this module and the
actions package).
"""

#: Alpha channel used for label colors in uploads/exports and list item
#: backgrounds.
LABEL_OPACITY = 128
