import copy
import logging
import pickle
from pathlib import Path
from typing import Dict, Optional

from runhouse.rns.blobs.blob import Blob, blob
from runhouse.rns.folders import Folder, folder
from runhouse.rns.hardware.cluster import Cluster
from runhouse.rns.utils.hardware import _current_cluster, _get_cluster_from
from runhouse.rns.utils.names import _generate_default_name

logger = logging.getLogger(__name__)


class File(Blob):
    def __init__(
        self,
        path: Optional[str] = None,
        name: Optional[str] = None,
        system: Optional[str] = Folder.DEFAULT_FS,
        data_config: Optional[Dict] = None,
        dryrun: bool = False,
        **kwargs,
    ):
        """
        Runhouse File object

        .. note::
                To build a File, please use the factory method :func:`file`.
        """
        super().__init__(name=name, dryrun=dryrun, system=system)
        self._filename = str(Path(path).name) if path else self.name
        # Use factory method so correct subclass for system is returned
        self._folder = folder(
            path=str(Path(path).parent) if path is not None else path,
            system=system,
            data_config=data_config,
            dryrun=dryrun,
        )
        self._cached_data = None

    @property
    def config_for_rns(self):
        config = super().config_for_rns
        file_config = {
            "path": self.path,  # pair with data source to create the physical URL
            "data_config": self.data_config,
        }
        config.update(file_config)
        return config

    @staticmethod
    def from_config(config: dict, dryrun=False):
        return Blob(**config, dryrun=dryrun)

    @property
    def system(self):
        return self._folder.system

    @system.setter
    def system(self, new_system):
        self._folder.system = new_system

    @property
    def path(self):
        return self._folder.path + "/" + self._filename

    @path.setter
    def path(self, new_path):
        self._folder.path = str(Path(new_path).parent)
        self._filename = str(Path(new_path).name)

    @property
    def data_config(self):
        return self._folder.data_config

    @data_config.setter
    def data_config(self, new_data_config):
        self._folder.data_config = new_data_config

    @property
    def fsspec_url(self):
        return self._folder.fsspec_url + "/" + self._filename

    def open(self, mode: str = "rb"):
        """Get a file-like (OpenFile container object) of the file data.
        User must close the file, or use this method inside of a with statement.

        Example:
            >>> with my_file.open(mode="wb") as f:
            >>>     f.write(data)
            >>>
            >>> obj = my_file.open()
        """
        return self._folder.open(self._filename, mode=mode)

    def to(
        self, system, path: Optional[str] = None, data_config: Optional[dict] = None
    ):
        """Return a copy of the file on the destination system and path.

        Example:
            >>> local_file = rh.file(data)
            >>> s3_file = file.to("s3")
            >>> cluster_file = file.to(my_cluster)
        """
        if system == "here":
            if not path:
                current_cluster_config = _current_cluster(key="config")
                if current_cluster_config:
                    system = Cluster.from_config(current_cluster_config)
                else:
                    system = None
            else:
                system = "file"

        system = _get_cluster_from(system)
        if (not system or isinstance(system, Cluster)) and not path:
            name = self.name or _generate_default_name(prefix="file")
            return Blob(name=name, system=system).write(self.fetch())

        new_file = copy.copy(self)
        new_file._folder = self._folder.to(
            system=system, path=path, data_config=data_config
        )
        return new_file

    def fetch(self, deserialize: bool = True):
        """Return the data for the user to deserialize.

        Example:
            >>> data = file.fetch()
        """
        self._cached_data = self._folder.get(self._filename)
        if deserialize:
            self._cached_data = pickle.loads(self._cached_data)
        return self._cached_data

    def _save_sub_resources(self):
        if isinstance(self.system, Cluster):
            self.system.save()

    def write(self, data, serialize: bool = True):
        """Save the underlying file to its specified fsspec URL.

        Example:
            >>> rh.file(system="s3", path="path/to/save").write(data)
        """
        self._folder.mkdir()
        if serialize:
            data = pickle.dumps(data)
        elif not isinstance(data, bytes):
            # Avoid TypeError: a bytes-like object is required
            raise TypeError(
                f"Cannot save file with data of type {type(data)}, data must be serialized or set serialize=True"
            )
        with self.open(mode="wb") as f:
            f.write(data)
        return self

    def rm(self):
        """Delete the file and the folder it lives in from the file system.

        Example:
            >>> file = rh.file(data, path="saved/path")
            >>> file.rm()
        """
        self._folder.rm(contents=[self._filename], recursive=False)

    def exists_in_system(self):
        """Check whether the file exists in the file system

        Example:
            >>> file = rh.file(data, path="saved/path")
            >>> file.exists_in_system()
        """
        return self._folder.fsspec_fs.exists(self.fsspec_url)


def file(
    data=None,
    name: Optional[str] = None,
    path: Optional[str] = None,
    system: Optional[str] = None,
    data_config: Optional[Dict] = None,
    dryrun: bool = False,
):
    """Returns a File object, which can be used to interact with the resource at the given path

    Args:
        data: File data. This should be a serializable object.
        name (Optional[str]): Name to give the file object, to be reused later on.
        path (Optional[str]): Path (or path) of the file object.
        system (Optional[str or Cluster]): File system or cluster name. If providing a file system this must be one of:
            [``file``, ``github``, ``sftp``, ``ssh``, ``s3``, ``gs``, ``azure``].
            We are working to add additional file system support.
        data_config (Optional[Dict]): The data config to pass to the underlying fsspec handler.
        dryrun (bool): Whether to create the File if it doesn't exist, or load a File object as a dryrun.
            (Default: ``False``)

    Returns:
        File: The resulting file.

    Example:
        >>> import runhouse as rh
        >>> import json
        >>> data = json.dumps(list(range(50))
        >>>
        >>> # Remote file with name and no path (saved to bucket called runhouse/blobs/my-file)
        >>> rh.file(name="@/my-file", data=data, system='s3').write()
        >>>
        >>> # Remote file with name and path
        >>> rh.file(name='@/my-file', path='/runhouse-tests/my_file.pickle', system='s3').save()
        >>>
        >>> # Local file with name and path, save to local filesystem
        >>> rh.file(data=data, path=str(Path.cwd() / "my_file.pickle")).write()
        >>>
        >>> # Local file with name and no path (saved to ~/.cache/blobs/my-file)
        >>> rh.file(name="~/my-file", data=data).write().save()

        >>> # Loading a file
        >>> my_local_file = rh.file(name="~/my_file")
        >>> my_s3_file = rh.file(name="@/my_file")
    """
    return blob(
        name=name,
        data=data,
        path=path,
        system=system,
        data_config=data_config or {},  # Trick to force blob factory to create a File
        dryrun=dryrun,
    )
