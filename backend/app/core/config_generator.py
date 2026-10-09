import dataclasses
import hashlib

import jinja2
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core import postfix_control
from app.core.clock import utcnow
from app.core.encryption import decrypt_secret
from app.core.permissions import enabled_senders_with_upstream, sender_login_map
from app.models.config_generation import ConfigGeneration
from app.models.enums import TlsMode, ValidationResult
from app.models.sender import Sender
from app.models.upstream import UpstreamAccount

_ENV = jinja2.Environment(
    loader=jinja2.PackageLoader("app", "templates"),
    autoescape=False,  # generating Postfix config text, not HTML
    keep_trailing_newline=True,
    undefined=jinja2.StrictUndefined,
)


# Where the postfix image's ca-certificates package puts the system trust
# store — main.cf's smtp_tls_CAfile unless settings.upstream_tls_ca_file
# overrides it.
_DEBIAN_CA_BUNDLE = "/etc/ssl/certs/ca-certificates.crt"


def _tab_join(*fields: str) -> str:
    return "\t".join(fields)


def _transport_name_for(account: UpstreamAccount) -> str:
    """Which master.cf transport a sender using this upstream account must
    route through — plain `smtp` unless a synthetic one is needed. Every
    routed sender gets an explicit entry, because main.cf's
    default_transport is an error transport: anything *without* an entry
    (an unrouted sender, the null sender) must bounce rather than fall
    through to direct-to-MX delivery (#151). A rate limit always wins the naming: an
    account needing pacing gets its own `rl_acct{id}` transport (carrying
    wrappermode too, if that account is also implicit-TLS), so it never
    fights over one sender with the shared `smtp_implicit_tls` transport
    from #57. Accounts that are implicit-TLS but not rate-limited keep
    using that existing shared transport completely unchanged."""
    if account.rate_limit_per_hour is not None:
        return f"rl_acct{account.id}"
    if account.tls_mode is TlsMode.implicit:
        return "smtp_implicit_tls"
    return "smtp"


def _rate_delay_seconds(rate_limit_per_hour: int) -> int:
    # Spaces deliveries evenly rather than enforcing an exact per-clock-
    # hour bucket — smoothing/pacing, not a hard quota (docs/configuration.md).
    return -(-3600 // rate_limit_per_hour)  # ceil(3600 / N), no float rounding


@dataclasses.dataclass
class RateLimitedAccountTransport:
    account_id: int
    implicit_tls: bool
    rate_delay_seconds: int


def _rate_limited_account_transports(db: Session) -> list[RateLimitedAccountTransport]:
    """One entry per distinct upstream account that needs a synthetic
    master.cf transport for pacing — deduplicated (multiple senders can
    share one account) and sorted by id for deterministic config output."""
    accounts: dict[int, UpstreamAccount] = {}
    for sender in enabled_senders_with_upstream(db):
        account = sender.upstream_account
        if account.rate_limit_per_hour is not None:
            accounts[account.id] = account
    return [
        RateLimitedAccountTransport(
            account_id=account.id,
            implicit_tls=account.tls_mode is TlsMode.implicit,
            rate_delay_seconds=_rate_delay_seconds(account.rate_limit_per_hour),
        )
        for account in sorted(accounts.values(), key=lambda a: a.id)
    ]


def _build_maps(db: Session) -> tuple[dict[str, str], list[str]]:
    """Renders the five lookup-map source files
    (postfix-architecture.md §4) plus a list of human-readable warnings for
    senders that can't currently produce a working map entry (e.g. their
    upstream account is disabled) — an invariant worth surfacing, not
    silently rendering broken config for (architecture.md §5)."""
    warnings: list[str] = []

    login_map = sender_login_map(db)
    sender_login_lines = [
        _tab_join(address, ",".join(usernames)) for address, usernames in sorted(login_map.items())
    ]

    relayhost_lines: list[str] = []
    sasl_passwd_lines: list[str] = []
    # Every routed sender gets an entry here, including the plain-`smtp`
    # majority: main.cf's default_transport is an error transport, so a
    # sender missing from this map bounces instead of being delivered
    # direct-to-MX (#151).
    sender_transport_lines: list[str] = []
    # smtp_tls_policy_maps is keyed by nexthop, i.e. per upstream account
    # (host:port), not per sender — several senders can share one account.
    # main.cf's default level is `secure` (verify the certificate and the
    # hostname); only accounts that explicitly opted out get `encrypt`.
    tls_policy: dict[str, str] = {}
    for sender in enabled_senders_with_upstream(db):
        account = sender.upstream_account
        relayhost_lines.append(_tab_join(sender.address, f"[{account.host}]:{account.port}"))
        password = decrypt_secret(account.encrypted_password)
        sasl_passwd_lines.append(_tab_join(sender.address, f"{account.username}:{password}"))
        # Empty nexthop after the colon — Postfix still resolves the
        # actual host:port via sender_dependent_relayhost_maps above,
        # this only selects which transport handles the sender.
        sender_transport_lines.append(_tab_join(sender.address, f"{_transport_name_for(account)}:"))
        if account.tls_skip_verify:
            tls_policy[f"[{account.host}]:{account.port}"] = "encrypt"

    all_senders = db.execute(select(Sender)).scalars().all()
    working_addresses = {s.address for s in enabled_senders_with_upstream(db)}
    for sender in all_senders:
        if not sender.enabled:
            continue
        if sender.address in working_addresses:
            continue
        account = sender.upstream_account
        reason = "no upstream account" if account is None else f"upstream account {account.name!r} is disabled"
        warnings.append(f"Sender {sender.address!r} is enabled but has {reason} — excluded from generated config.")

    maps = {
        "sender_login": "\n".join(sender_login_lines) + ("\n" if sender_login_lines else ""),
        "sender_relayhost": "\n".join(relayhost_lines) + ("\n" if relayhost_lines else ""),
        "sasl_passwd": "\n".join(sasl_passwd_lines) + ("\n" if sasl_passwd_lines else ""),
        "sender_transport": "\n".join(sender_transport_lines) + ("\n" if sender_transport_lines else ""),
        "tls_policy": "".join(f"{_tab_join(nexthop, level)}\n" for nexthop, level in sorted(tls_policy.items())),
    }
    return maps, warnings


def _render_config(db: Session) -> tuple[str, str]:
    settings = get_settings()
    main_cf = _ENV.get_template("main.cf.j2").render(
        myhostname=settings.submission_host,
        mydomain=settings.submission_host,
        policy_service_port=settings.policy_service_port,
        submission_auth_rate_limit_per_minute=settings.submission_auth_rate_limit_per_minute,
        upstream_tls_ca_file=settings.upstream_tls_ca_file or _DEBIAN_CA_BUNDLE,
    )
    master_cf = _ENV.get_template("master.cf.j2").render(
        rate_limited_accounts=_rate_limited_account_transports(db),
    )
    return main_cf, master_cf


def _checksum(main_cf: str, master_cf: str) -> str:
    return hashlib.sha256((main_cf + "\0" + master_cf).encode("utf-8")).hexdigest()


def _maps_checksum(maps: dict[str, str]) -> str:
    joined = "\0".join(f"{name}\0{content}" for name, content in sorted(maps.items()))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def current_state_checksums(db: Session) -> tuple[str, str]:
    """What `generate_and_apply` would produce right now (main/master
    checksum, maps checksum), computed with no side effects and without
    calling the control surface — used by health checks
    (architecture.md §7) to detect "DB state changed since the last
    successful generation" drift."""
    main_cf, master_cf = _render_config(db)
    maps, _ = _build_maps(db)
    return _checksum(main_cf, master_cf), _maps_checksum(maps)


@dataclasses.dataclass
class GenerationOutcome:
    generation_id: int
    success: bool
    validation_detail: str
    reloaded: bool
    warnings: list[str]


def generate_and_apply(db: Session, *, triggered_by_admin_id: int | None, dry_run: bool = False) -> GenerationOutcome:
    """The full architecture.md §5 pipeline: render -> (dry_run stops
    here) -> validate+install+maybe-reload via the control surface ->
    record a config_generations row. `dry_run=True` is `relay
    validate-config`'s mode — it renders and would validate, but never
    installs (the control surface's apply_config always installs on
    success, so a true dry-run only renders locally and skips the RPC
    entirely; see the CLI command for how that's surfaced)."""
    main_cf, master_cf = _render_config(db)
    maps, warnings = _build_maps(db)
    checksum = _checksum(main_cf, master_cf)
    maps_checksum = _maps_checksum(maps)

    last_good = (
        db.query(ConfigGeneration)
        .filter(ConfigGeneration.validation_result == ValidationResult.pass_, ConfigGeneration.applied.is_(True))
        .order_by(ConfigGeneration.generated_at.desc())
        .first()
    )
    reload_if_main_changed = last_good is None or last_good.checksum != checksum

    if dry_run:
        return GenerationOutcome(
            generation_id=-1,
            success=True,
            validation_detail="Dry run — not sent to the Postfix control surface.",
            reloaded=False,
            warnings=warnings,
        )

    if not reload_if_main_changed:
        # Checksum-only used to be the whole story here, but that assumes
        # Postfix is already running with that exact config. It isn't,
        # whenever the postfix container has restarted (a crash, a host
        # reboot, `docker compose restart postfix`) without app's own
        # database changing — real testing hit this: config_generations
        # still pointed at the last-applied checksum, so a fresh,
        # un-started Postfix process was never told to start at all, with
        # no supported way to recover short of operating on the container
        # directly.
        try:
            reload_if_main_changed = not postfix_control.status().running
        except postfix_control.PostfixControlError:
            # Unreachable is a separate failure mode the RPC below will
            # hit (and report) the same way — default to attempting a
            # start rather than silently assuming it's fine.
            reload_if_main_changed = True

    result = postfix_control.apply_config(
        main_cf=main_cf, master_cf=master_cf, maps=maps, reload_if_main_changed=reload_if_main_changed
    )

    detail_parts = [result.validation_detail] if result.validation_detail else []
    detail_parts.extend(warnings)
    validation_detail = "\n".join(detail_parts) if detail_parts else None

    generation = ConfigGeneration(
        generated_at=utcnow(),
        triggered_by_admin_id=triggered_by_admin_id,
        checksum=checksum,
        maps_checksum=maps_checksum,
        validation_result=ValidationResult.pass_ if result.success else ValidationResult.fail,
        validation_detail=validation_detail,
        applied=result.success,
        reload_triggered=result.reloaded,
    )
    db.add(generation)
    db.commit()
    db.refresh(generation)

    return GenerationOutcome(
        generation_id=generation.id,
        success=result.success,
        validation_detail=validation_detail or "",
        reloaded=result.reloaded,
        warnings=warnings,
    )
