from PyQt5.QtWidgets import QTreeWidgetItem


def make_tree_item(values):
    return QTreeWidgetItem([str(v) for v in values])
