document.addEventListener("DOMContentLoaded", function() {
    let selector = document.getElementById("template-selector");
    let textarea = document.getElementById("id_content");

    if (selector && textarea) {
        selector.addEventListener("change", function() {
            if (this.value) {
                textarea.value = this.value + textarea.value; // Prepend template text
                this.selectedIndex = 0; // Reset dropdown after selection
            }
        });
    }
});