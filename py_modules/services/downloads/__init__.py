"""ROM downloads — from a frontend request to a recorded install on disk.

The download engine and its queue (``service.py``) over the layout an extracted
multi-file ROM is left in (``disc_layout.py``). Consumers import the service;
the arranger is a collaborator the service owns.
"""

from services.downloads.service import DownloadService, DownloadServiceConfig

__all__ = ["DownloadService", "DownloadServiceConfig"]
