/**
 * Minuteur Cloudflare — reveille le watcher plus vite que le cron GitHub.
 *
 * Pourquoi : GitHub bride les workflows planifies frequents. Un cron regle
 * sur 5 minutes ne se declenche en pratique que toutes les 15 a 19 minutes
 * (mesure sur le repo). Les declenchements par evenement, eux, ne sont pas
 * brides et partent en quelques secondes.
 *
 * Ce Worker ne fait qu'une chose : poster un evenement "verifier" sur le
 * repo. Tout le travail reste dans GitHub Actions.
 *
 * Secrets a definir dans Cloudflare (Settings > Variables and Secrets) :
 *   GITHUB_TOKEN  jeton fine-grained, ce repo seulement, "contents: write"
 *   GITHUB_REPO   par exemple razotrad3-debug/astro-alerts
 */

async function reveiller(env) {
  const depot = env.GITHUB_REPO;
  const reponse = await fetch(`https://api.github.com/repos/${depot}/dispatches`, {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${env.GITHUB_TOKEN}`,
      "Accept": "application/vnd.github+json",
      // GitHub refuse les requetes sans User-Agent.
      "User-Agent": "astro-alerts-minuteur",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ event_type: "verifier" }),
  });

  // 204 = accepte. Tout le reste merite d'apparaitre dans les logs du Worker.
  if (reponse.status !== 204) {
    const detail = await reponse.text();
    console.log(`GitHub a repondu ${reponse.status} : ${detail.slice(0, 200)}`);
  }
  return reponse.status;
}

export default {
  // Appele par le cron Cloudflare.
  async scheduled(evenement, env, ctx) {
    ctx.waitUntil(reveiller(env));
  },

  // Permet de tester a la main en ouvrant l'URL du Worker.
  async fetch(requete, env) {
    const code = await reveiller(env);
    return new Response(
      code === 204 ? "Signal envoye au watcher.\n"
                   : `Echec : GitHub a repondu ${code}.\n`,
      { status: code === 204 ? 200 : 500 },
    );
  },
};
