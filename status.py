def format_progress_bar(filename, percentage, done, total_size, status, eta, speed, elapsed, user_mention, user_id, aria2p_gid):
    bar_length = 10
    filled_char = "▪️"
    empty_char = "▫️"
    filled_length = int(bar_length * percentage / 100)
    bar = filled_char * filled_length + empty_char * (bar_length - filled_length)

    # Size formatter
    def format_size(size):
        size = float(size)
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if size < 1024:
                return f"{size:.2f} {unit}"
            size /= 1024

    # ETA Short
    def format_eta(seconds):
        seconds = int(float(seconds))
        if seconds < 60:
            return f"{seconds}s"
        elif seconds < 3600:
            return f"{seconds//60}m {seconds%60}s"
        else:
            h = seconds // 3600
            m = (seconds % 3600) // 60
            return f"{h}h {m}m"

    eta = format_eta(eta)

    return (
        f"📄 <b>{filename}</b>\n"
        f"[{bar}]\n"
        f"<b>Progress:</b> {percentage:.2f}%\n"
        f"<b>Stutes:</b> {status}\n"
        f"<b>Size:</b> {format_size(done)} of {format_size(total_size)}\n"
        f"<b>Speed:</b> {format_size(speed)}/s\n"
        f"<b>ETA:</b> {eta}"
    )
  
