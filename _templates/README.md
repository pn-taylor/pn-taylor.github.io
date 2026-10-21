# Templates

Copy one of these to start something new. This folder isn't published (Jekyll skips
folders starting with `_` that aren't collections).

| File | Copy to | Name it |
| --- | --- | --- |
| `blog-post.md` | `_posts/<year>/` | `YYYY-MM-DD-title.md` |
| `review-book.md` | `_reviews/` | `YYYY-MM-DD-title.md` |
| `review-film.md` | `_reviews/` | `YYYY-MM-DD-title.md` |
| `review-tv.md` | `_reviews/` | `YYYY-MM-DD-title.md` |
| `review-game.md` | `_reviews/` | `YYYY-MM-DD-title.md` |
| `review-gadget.md` | `_reviews/` | `YYYY-MM-DD-title.md` |
| `note.md` | `_notes/` | `YYYY-MM-DD-short-name.md` |

The filename's date and title become the post's date and web address
(`/blog/title`, `/review/title`, or `/note/YYYY-MM-DD-short-name` for notes), so pick the title part carefully.

## Things that happen on their own

- **Time of day**: when you push a new post dated today, a GitHub workflow adds the
  time it was committed to `date:` and commits that back, so pull before editing it
  again. Leave `date:` out, or date-only, and it's handled.
- **Future dates**: a post dated in the future goes live (and is announced) at
  about 00:05 Canberra time on that day.
- **Excerpt**: the first paragraph is used automatically. Only add `excerpt:` if the
  post starts with a heading or image, or you want a different summary.
- **Images**: anything over 1 MB or 2000px is shrunk after you push, and an image whose
  contents don't match its extension (e.g. a WebP saved as .jpg) is converted.

## Review fields

Everything is optional except `title` and `rating`.

| Field | Shows as | Notes |
| --- | --- | --- |
| `rating` | Stars + "x out of 5" | 0–5, halves allowed (`3.5`) |
| `cover` | Cover image | Tall images (2:3, like a book cover or poster) look best. Put in `/images/reviews/` |
| `cover_alt` | | Describes the cover for screen readers |
| `creator` | **By** | Author, director, developer, maker |
| `category` | **Category** | Groups the Reviews page: Book, Film, TV, Game, Gadget |
| `platform` | **On** | Where you read/watched/played it |
| `details` | Any label you like | Extra lines under the cover, in the order written. Lists show comma-separated |
| `verdict` | **Verdict:** after the review | One line; also used in the archive |
| `pros` / `cons` | "What worked" / "What didn't" | Lists |
| `post_to_socials` | | `true` to announce on Bluesky, Mastodon and Threads |
