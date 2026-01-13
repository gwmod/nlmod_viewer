def classFactory(iface):
    from .nlmod_inspector import NlmodInspector
    return NlmodInspector(iface)
