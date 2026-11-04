"""Select ingestion authority explicitly; a mode never grants host access."""


def validate_mode(parser, args):
    """Reject incomplete or mixed selections before loading configuration or source."""
    folder = (args.folder_context, args.folder_index, args.folder_output)
    folder_options = (any(value is not None for value in folder) or args.folder_source_ref is not None
                      or args.folder_repo is not None or getattr(args, 'folder_queries', None) is not None
                      or getattr(args, 'folder_existing_sha256', None) is not None)
    entry_folder = getattr(args, 'entry_folder', None)
    entry_index = getattr(args, 'entry_index', None)
    if entry_index is not None and entry_folder is None:
        parser.error('entry-index requires entry-folder')
    if args.mode != 'working-tree' and (entry_folder is not None or entry_index is not None):
        parser.error('working-tree entry selection requires --mode working-tree')
    if entry_folder is not None and (getattr(args, 'query', None) is not None or getattr(args, 'allow_unrequested', False)):
        parser.error('working-tree folder entry requires a source and requested result')
    if args.mode == 'folder':
        if not all(folder) or not args.approved_revision or args.policy_context is not None:
            parser.error('folder mode requires approved-revision, folder-context, folder-index and folder-output; policy-context requires --mode v1')
        if hasattr(args, 'source') and not args.source:
            parser.error('folder mode requires an explicit source')
        if getattr(args, 'query', None) is not None or getattr(args, 'allow_unrequested', False):
            parser.error('folder mode requires a source-bound request and result')
    elif args.mode == 'v1':
        if folder_options or not args.approved_revision or not args.policy_context:
            parser.error('v1 mode requires approved-revision and policy-context and forbids folder selections')
    elif args.mode == 'working-tree':
        if folder_options or args.approved_revision is not None or args.policy_context is not None:
            parser.error('working-tree mode forbids approved and folder selections')
    else:
        parser.error('unknown ingestion mode')
