import json
import re
import xml.etree.ElementTree as ET

from django.test import TestCase, override_settings

from store.models import BlogPost, User


@override_settings(SECURE_SSL_REDIRECT=False, ALLOWED_HOSTS=["testserver"],
                   STORAGES={"staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}})
class BlogSEOTests(TestCase):
    def test_published_guides_have_links_canonical_metadata_and_valid_schema(self):
        posts = BlogPost.objects.filter(published=True)
        self.assertEqual(posts.count(), 4)
        listing = self.client.get("/blog/")
        self.assertEqual(listing.status_code, 200)
        for post in posts:
            self.assertContains(listing, post.get_absolute_url())
            response = self.client.get(post.get_absolute_url() + "?source=test")
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, '<link rel="canonical" href="http://testserver' + post.get_absolute_url() + '">')
            schema = json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>', response.content.decode(), re.S).group(1))
            self.assertEqual(schema["headline"], post.title)
            self.assertNotIn("<p>", schema["description"])
            self.assertNotIn("?source", schema["mainEntityOfPage"]["@id"])

    def test_drafts_are_excluded_from_sitemap_and_public_pages(self):
        author = User.objects.first()
        draft = BlogPost.objects.create(title="Private draft", slug="private-draft", author=author, content="Draft")
        response = self.client.get("/sitemap.xml")
        self.assertEqual(response.status_code, 200)
        root = ET.fromstring(response.content)
        self.assertEqual(len(root), 7)
        self.assertNotContains(response, draft.slug)
        self.assertEqual(self.client.get(draft.get_absolute_url()).status_code, 404)
        self.assertContains(self.client.get("/robots.txt"), "Sitemap: http://testserver/sitemap.xml")

    def test_article_schema_escapes_script_endings_and_quotes(self):
        post = BlogPost.objects.first()
        post.title = 'A "quoted" guide </script><script>alert(1)</script>'
        post.save()
        response = self.client.get(post.get_absolute_url())
        schema = json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>', response.content.decode(), re.S).group(1))
        self.assertEqual(schema["headline"], post.title)
