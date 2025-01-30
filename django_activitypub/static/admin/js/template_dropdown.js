document.addEventListener("DOMContentLoaded", function() {
    var dropdown = document.getElementById("template-selector");
    var contentField = document.getElementById("id_content"); // Adjust based on Django field ID

    if (dropdown && contentField) {
        dropdown.addEventListener("change", function() {
            var selectedTemplate = dropdown.value;

            if (selectedTemplate) {
                contentField.value = ""; // Clears the text field before adding the template
                contentField.value = selectedTemplate;
            }
        });
    }
});