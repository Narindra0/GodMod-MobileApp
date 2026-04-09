# Import absolus pour éviter les erreurs d'imports relatifs
import sys
import os

try:
    from prisma import analyzers, engine, selection
except ImportError:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
    from prisma import analyzers, engine, selection
