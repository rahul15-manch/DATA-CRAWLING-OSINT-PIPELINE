import sys
import os

# Add the 'pillar1' subdirectory to sys.path so pytest can find 'search' and 'query' packages
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "pillar1")))
