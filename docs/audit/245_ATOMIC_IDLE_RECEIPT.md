# Complete cold-idle receipts before publication

The location owner saves the world, publishes a PID receipt, withdraws its status and requests quit. The native Master's lzm_host.h consumes that receipt only after the matching process exits, changing its mode to dormant/auto for demand wakeup. A direct stdio write previously exposed a partial final file and ignored fprintf failure; failed fclose could leave a complete-looking receipt even though no idle quit was requested.

cluster_idle_receipt now writes a PID-specific temporary sibling, checks full WriteFile size, FlushFileBuffers and CloseHandle, then replaces the final name with MoveFileExA. Failed publication cleans the temporary sibling and preserves any prior final file. cluster_idle_exit retains world-save/admission/client protection, the60second retry and status-withdrawal cleanup before quit. No Master protocol or player persistence changes.

The existing Windows CI fixture compiles the actual helper and idle function. It injects open/write/short-write/flush/close/publish errors with and without a previous receipt, checks no newly visible partial receipt or leaked handles, verifies a real Windows sharing violation, and executes failed receipt→60second backoff→successful saved stop. Existing timer-wrap/connecting-client/admission/status cases remain. Native validation runs only in CI, not locally; game acceptance and full DX11/DX8 rebuild remain separate. No installation/publication or game processes are authorized by this patch.

Validated24November: exact94bac2e4539523ecd9a73c8d5a9ea71e69f5c7e2 Foundation45421101758 all4 SUCCESS. Actual receipt fault cases PASS; run/review/raw log retained in private vault Evidence/CI/Idle_20261124. No full rebuild, install, publication or game acceptance.
