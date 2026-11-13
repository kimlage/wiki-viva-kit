"""Select ingestion authority explicitly; a mode never grants host access."""


def validate_mode(parser, args):
    """Reject incomplete or mixed selections before loading configuration or source."""
    folder = (args.folder_context, args.folder_index, args.folder_output)
    folder_options = (any(value is not None for value in folder) or args.folder_source_ref is not None
                      or args.folder_repo is not None or getattr(args, 'folder_queries', None) is not None
                      or getattr(args, 'folder_existing_sha256', None) is not None)
<<<<<<< ours
    if args.mode is None:
        if folder_options:
            args.mode = 'folder'
        elif args.approved_revision is not None or args.policy_context is not None:
            args.mode = 'v1'
        else:
            args.mode = 'working-tree'
=======
    entry_folder = getattr(args, 'entry_folder', None)
    entry_index = getattr(args, 'entry_index', None)
    if entry_index is not None and entry_folder is None:
        parser.error('entry-index requires entry-folder')
    if args.mode != 'working-tree' and (entry_folder is not None or entry_index is not None):
        parser.error('working-tree entry selection requires --mode working-tree')
    if entry_folder is not None and (getattr(args, 'query', None) is not None or getattr(args, 'allow_unrequested', False)):
        parser.error('working-tree folder entry requires a source and requested result')
>>>>>>> theirs
    if args.mode == 'folder':
        if args.folder_context and args.folder_index is None:
            from wiki_core.folder_declarations_v2 import selected_folder_index
            try:
                args.folder_index = selected_folder_index(args.folder_context, None)
            except ValueError:
                parser.error('folder index selection unavailable')
            folder = (args.folder_context, args.folder_index, args.folder_output)
        if not all(folder) or not args.approved_revision or args.policy_context is not None:
            parser.error('folder mode requires approved-revision, folder-context and folder-output; root index must be explicit and policy-context requires --mode v1')
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
