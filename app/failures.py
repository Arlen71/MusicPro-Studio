"""Typed worker failures: a bad input must not be confused with a bad GPU."""

class UserError(Exception): pass
class Cancelled(Exception): pass
class EncoderError(UserError): pass
class StorageError(UserError): pass


class SourceError(UserError):
    def __init__(self, asset, role, reason):
        self.asset = asset
        self.role = role
        self.reason = str(reason)
        super().__init__(f'{asset.get("name", asset.get("path", "Manba"))}: {reason}')


def error_record(error):
    result = {'type': 'render', 'message': str(error)}
    if isinstance(error, SourceError):
        result.update(type='source', asset=error.asset, role=error.role, message=error.reason)
    elif isinstance(error, EncoderError): result['type'] = 'encoder'
    elif isinstance(error, StorageError): result['type'] = 'storage'
    return result


def raise_record(record):
    if record.get('type') == 'source':
        raise SourceError(record['asset'], record['role'], record['message'])
    cls = {'encoder': EncoderError, 'storage': StorageError}.get(record.get('type'), UserError)
    raise cls(record.get('message', 'Render jarayoni uzildi.'))


def check_storage_error(error):
    text = str(error).lower()
    if getattr(error, 'errno', None) == 28 or any(s in text for s in (
        'no space left', 'disk full', 'not enough space', 'read-only file system',
        'error opening output', 'error writing trailer', 'av_interleaved_write_frame',
    )):
        raise StorageError(str(error)) from error
