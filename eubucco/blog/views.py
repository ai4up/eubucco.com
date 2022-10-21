from django.shortcuts import render

from .models import Post

# from django.views.decorators.cache import cache_page


# @cache_page(60 * 60)
def index(request):
    posts = Post.objects.all().values("title", "slug", "created_on", "summary")
    return render(request, "blog/index.html", {"posts": posts})


# @cache_page(60 * 60)
def get_post(request, slug):
    post = Post.objects.filter(slug=slug).first()
    return render(request, "blog/post.html", {"post": post})
