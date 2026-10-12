from django.core.cache import cache


def too_many(key, limit=8, window=300):
    """Count a hit against ``key`` and report whether the limit is exceeded.

    ``cache.add`` + ``cache.incr`` keeps the counter atomic on shared caches
    (Redis, Memcached), so parallel requests cannot all slip under the limit.
    """
    key = f"rl:{key}"
    if cache.add(key, 1, window):
        return False
    try:
        count = cache.incr(key)
    except ValueError:  # expired between add and incr
        cache.set(key, 1, window)
        return False
    return count > limit


def client_ip(request):
    from django.conf import settings

    if getattr(settings, "TRUST_X_FORWARDED_FOR", False):
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
        if forwarded:
            return forwarded.split(",")[0].strip()[:45]
    return (request.META.get("REMOTE_ADDR") or "unknown")[:45]
