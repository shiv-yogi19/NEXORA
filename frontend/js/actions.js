// Shared file actions (favorites, watchlist, download). Created By Shiv Yogi.
import { get, post, del, fileUrl, ApiError, NetworkError } from "./api.js";
import { h, toast } from "./ui.js";

export async function toggleFavorite(item) {
  try {
    if (item.favorite) await del("/favorites/" + item.id); else await post("/favorites", { file_id: item.id });
    item.favorite = !item.favorite;
    toast(item.favorite ? "Added to Favorites." : "Removed from Favorites.", "ok");
  } catch (e) { toast(errText(e, "Could not update Favorites."), "error"); }
  return item.favorite;
}
export async function toggleWatchlist(item) {
  try {
    if (item.watchlist) await del("/watchlist/" + item.id); else await post("/watchlist", { file_id: item.id });
    item.watchlist = !item.watchlist;
    toast(item.watchlist ? "Added to Watchlist." : "Removed from Watchlist.", "ok");
  } catch (e) { toast(errText(e, "Could not update Watchlist."), "error"); }
  return item.watchlist;
}

/** Checks that the server will serve the file, then hands the transfer to the browser's download manager.
 *  The page cannot see when the browser finishes, so it never claims completion. */
export async function downloadFile(item) {
  const url = fileUrl(item.id, "download");
  try {
    const res = await fetch(url, { method: "HEAD", credentials: "include", cache: "no-store" });
    if (!res.ok) throw new ApiError(res.status, res.status === 404 ? "not_found" : "error", res.status === 404 ? "That file is no longer on the phone. Rescan the library from Storage." : res.status === 401 ? "Your session ended. Log in again." : "The server refused the download (" + res.status + ").");
  } catch (e) {
    toast(e instanceof ApiError ? e.message : "Could not reach the server, so the download did not start.", "error");
    return false;
  }
  const a = h("a", { href: url, rel: "noopener", download: item.name });
  document.body.append(a); a.click(); a.remove();
  toast(`Download requested: ${item.name}. Your browser shows its progress and result in its downloads list.`, "info", { ms: 6000 });
  return true;
}

export function errText(e, fallback) {
  if (e instanceof ApiError) return e.message || fallback;
  if (e instanceof NetworkError) return e.message || "Could not reach the server.";
  return fallback;
}
export { get };
