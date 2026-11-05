/* Keep all meeting cards in one chronological DOM order. No data fetching. */
(() => {
  const sortMeetings = () => {
    const list = document.querySelector('section[aria-label="Meetings"]');
    if (!list) return;
    const cards = Array.from(list.children).filter(node =>
      node.matches('article.meeting-card, article.legacy-meeting-card'));
    const date = card => card.querySelector('.meeting-summary time[datetime]')?.getAttribute('datetime')?.slice(0, 10) || '';
    cards.sort((left, right) => date(right).localeCompare(date(left)));
    cards.forEach(card => list.appendChild(card));
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', sortMeetings, { once: true });
  else sortMeetings();
})();
