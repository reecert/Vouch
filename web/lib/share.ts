/**
 * Share metadata — what a link to a profile reveals before anyone opens it.
 *
 * An unfurled link is not a preview of the document; it is a second, worse copy of it. Slack,
 * LinkedIn, iMessage and X fetch the card once and serve it from their own caches
 * indefinitely, so it is read by everyone in a channel rather than the one person who
 * follows the link, it arrives without the denominators, confounds and limitations the
 * document spends its whole length establishing, and unpublishing the export cannot
 * withdraw it. A verdict or an email placed here outlives the profile it came from.
 *
 * So the card is branded and content-free (see `web/og/card.html`), and the text that
 * travels with it carries only counts: how much evidence was read, over how many
 * dimensions. Nothing identifying, nothing evaluative.
 *
 * `profileShareMetadata` takes those counts as arguments rather than taking a `Profile`.
 * That is the enforcement: the subject's address and every verdict are not in scope here,
 * so a later edit cannot casually interpolate one. It is the same move as `Profile` having
 * no aggregate-score field — the shape refuses it, rather than a comment asking nicely.
 */
import type { Metadata } from "next";

/** Absolute base for canonical and og:image; unfurlers reject relative URLs. */
export const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000";

export const SHARE_CARD = {
  url: "/og.png",
  width: 1200,
  height: 630,
  alt: "vouch — engineering capability profile. It supports a hiring decision; it does not make one.",
};

function plural(n: number, noun: string): string {
  return `${n} ${noun}${n === 1 ? "" : "s"}`;
}

export function profileShareMetadata(
  id: string,
  nCommits: number,
  nDimensions: number,
): Metadata {
  const path = `/p/${id}`;
  // The id, not the subject: a share link has to be distinguishable in a tab strip and in a
  // cached unfurl, and only one of those two can be un-shared later.
  const title = `Profile ${id.slice(0, 8)}`;
  const description =
    `${plural(nCommits, "commit")} inspected across ` +
    `${plural(nDimensions, "dimension")}, with the denominators and the limits stated. ` +
    `No overall score.`;

  return {
    title,
    description,
    alternates: { canonical: path },
    // openGraph and twitter replace the parent's wholesale rather than merging, so the
    // card has to be repeated here or a profile link unfurls with no image at all.
    openGraph: {
      title: `${title} · vouch`,
      description,
      url: path,
      siteName: "vouch",
      type: "article",
      images: [SHARE_CARD],
    },
    twitter: {
      card: "summary_large_image",
      title: `${title} · vouch`,
      description,
      images: [SHARE_CARD],
    },
  };
}
