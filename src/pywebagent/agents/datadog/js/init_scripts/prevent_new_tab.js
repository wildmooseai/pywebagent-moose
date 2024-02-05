
// Preventing navigations on the Datadog website, such as "Create new Monitor", from 
// opening new tabs (which destroys the navigation context for Playwright). Instead,
// we navigate to the destination in the current tab.
document.addEventListener('click', function(event) {
    // Ensure the clicked element is an anchor tag
    var target = event.target.closest('a');
  
    if (target && target.target === '_blank') {
      // Prevent the default behavior of opening a new tab
      event.preventDefault();
  
      // Navigate the current page to the href of the anchor tag
      window.location.href = target.href;
    }
  });