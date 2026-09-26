# www

deadlysyn.com static content

## how to use

blog.py is now in the root of the zip. It needs only Python 3.8 or newer, with no packages to install.

How it works. Each post's own file is the source of truth, and you edit only three things in it:

- the date, keywords (your tags), and description meta tags in the `<head>`
- the title inside `<h1 class="name">`
- the body, between `<!-- post:start -->` and `<!-- post:end -->``

Everything else is regenerated when you run ./blog.py build: each post's surrounding page and older/newer links, the blog index, the tag pages, both RSS feeds, and the sitemap. Hand edits outside those three places get overwritten, which is what keeps every page consistent.

Writing a new post:

```
./blog.py new "Post Title" --tags aws,go   # creates blog/posts/post-title/ as a draft
# write the body, then delete the <meta name="draft"> line
./blog.py highlight post-title             # optional: color the code blocks
./blog.py build
python3 -m http.server 8000                # preview at localhost:8000
```

Drafts get a full page you can preview, but they stay out of the index, feeds, sitemap, and older/newer links until you remove the draft line. Removing a post and rebuilding updates everything, and a tag left with no posts redirects to the tag list instead of going stale. Each build lists the files it changed and warns about any broken internal links. Running it twice in a row changes nothing, so your git diffs only show real changes. ./blog.py list shows all posts and drafts.

A few things to know:

- highlight needs Pygments (pip install pygments). Without it, code blocks still display fine, just without colors. Everything else uses only the standard library.
- Existing descriptions were filled in from each post's first paragraph. Skim them when you get a chance. For example, Beware of Shadows picked up your struck-through joke as if it were normal text, which reads oddly in search results.
- blog.py sits in the web root, so it will be publicly downloadable unless your deploy excludes it. That's harmless, but you can move it up a directory if you prefer. It finds the blog/ folder next to itself, so the site folder would need to move with it.
