from django import forms
from .models import Review

class ReviewForm(forms.ModelForm):
    class Meta:
        model = Review
        fields = ['name', 'email', 'location', 'rating', 'comment']  # ✅ photo removed
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'Your Full Name'}),
            'email': forms.EmailInput(attrs={'placeholder': 'Your Email Address'}),
            'location': forms.TextInput(attrs={'placeholder': 'Your City/State (optional)'}),
            'rating': forms.NumberInput(attrs={'min': 1, 'max': 5}),
            'comment': forms.Textarea(attrs={'rows': 4, 'placeholder': 'Share your experience...'}),
        }
        labels = {
            'name': 'Name',
            'email': 'Email',
            'location': 'Location',
            'rating': 'Rating (1-5)',
            'comment': 'Your Review',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields:
            self.fields[field].widget.attrs.update({'class': 'form-control'})
