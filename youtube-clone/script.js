// Sample video data with real avatars
const videos = [
    {
        id: 1,
        title: "Building a Modern Website in 2024 - Complete Tutorial",
        thumbnail: "https://picsum.photos/seed/code1/640/360",
        duration: "24:35",
        channelName: "CodeMaster Pro",
        channelInitial: "C",
        channelAvatar: "https://api.dicebear.com/7.x/avataaars/svg?seed=CodeMaster",
        views: "1.2M views",
        postedAt: "2 days ago"
    },
    {
        id: 2,
        title: "Top 10 Programming Languages to Learn This Year",
        thumbnail: "https://picsum.photos/seed/tech2/640/360",
        duration: "15:20",
        channelName: "Tech Trends",
        channelInitial: "T",
        channelAvatar: "https://api.dicebear.com/7.x/avataaars/svg?seed=TechTrends",
        views: "890K views",
        postedAt: "5 days ago"
    },
    {
        id: 3,
        title: "Relaxing Music for Coding - 10 Hours Study Music",
        thumbnail: "https://picsum.photos/seed/lofi3/640/360",
        duration: "10:00:00",
        channelName: "LoFi Beats",
        channelInitial: "L",
        channelAvatar: "https://api.dicebear.com/7.x/avataaars/svg?seed=LoFi",
        views: "5.4M views",
        postedAt: "1 week ago"
    },
    {
        id: 4,
        title: "Building an AI Chatbot with Python - Full Guide",
        thumbnail: "https://picsum.photos/seed/python4/640/360",
        duration: "45:12",
        channelName: "Python Dev",
        channelInitial: "P",
        channelAvatar: "https://api.dicebear.com/7.x/avataaars/svg?seed=PythonDev",
        views: "2.1M views",
        postedAt: "3 days ago"
    },
    {
        id: 5,
        title: "Epic Gaming Highlights - Best Moments Compilation",
        thumbnail: "https://picsum.photos/seed/game5/640/360",
        duration: "32:48",
        channelName: "Gaming Vault",
        channelInitial: "G",
        channelAvatar: "https://api.dicebear.com/7.x/avataaars/svg?seed=GamingVault",
        views: "3.8M views",
        postedAt: "1 day ago"
    },
    {
        id: 6,
        title: "Travel Vlog: Exploring Tokyo, Japan",
        thumbnail: "https://picsum.photos/seed/travel6/640/360",
        duration: "18:25",
        channelName: "Wanderlust",
        channelInitial: "W",
        channelAvatar: "https://api.dicebear.com/7.x/avataaars/svg?seed=Wanderlust",
        views: "756K views",
        postedAt: "2 weeks ago"
    },
    {
        id: 7,
        title: "Full Body Workout - No Equipment Needed",
        thumbnail: "https://picsum.photos/seed/fitness7/640/360",
        duration: "28:00",
        channelName: "FitLife",
        channelInitial: "F",
        channelAvatar: "https://api.dicebear.com/7.x/avataaars/svg?seed=FitLife",
        views: "1.9M views",
        postedAt: "4 days ago"
    },
    {
        id: 8,
        title: "Cooking Masterclass: Italian Pasta Recipes",
        thumbnail: "https://picsum.photos/seed/cooking8/640/360",
        duration: "22:15",
        channelName: "Chef's Kitchen",
        channelInitial: "C",
        channelAvatar: "https://api.dicebear.com/7.x/avataaars/svg?seed=ChefKitchen",
        views: "543K views",
        postedAt: "1 week ago"
    },
    {
        id: 9,
        title: "Nature 4K - Relaxing Forest & Wildlife",
        thumbnail: "https://picsum.photos/seed/nature9/640/360",
        duration: "1:00:00",
        channelName: "Nature World",
        channelInitial: "N",
        channelAvatar: "https://api.dicebear.com/7.x/avataaars/svg?seed=NatureWorld",
        views: "8.2M views",
        postedAt: "3 weeks ago"
    },
    {
        id: 10,
        title: "JavaScript Crash Course - Learn in 60 Minutes",
        thumbnail: "https://picsum.photos/seed/js10/640/360",
        duration: "58:42",
        channelName: "Web Dev Simplified",
        channelInitial: "W",
        channelAvatar: "https://api.dicebear.com/7.x/avataaars/svg?seed=WebDev",
        views: "4.5M views",
        postedAt: "6 days ago"
    },
    {
        id: 11,
        title: "Minecraft Build Challenge - 24 Hour Stream",
        thumbnail: "https://picsum.photos/seed/minecraft11/640/360",
        duration: "24:00:00",
        channelName: "Block Builder",
        channelInitial: "B",
        channelAvatar: "https://api.dicebear.com/7.x/avataaars/svg?seed=BlockBuilder",
        views: "12M views",
        postedAt: "5 hours ago"
    },
    {
        id: 12,
        title: "Space Documentary - Journey to the Edge of Universe",
        thumbnail: "https://picsum.photos/seed/space12/640/360",
        duration: "52:18",
        channelName: "Cosmos HD",
        channelInitial: "C",
        channelAvatar: "https://api.dicebear.com/7.x/avataaars/svg?seed=Cosmos",
        views: "6.7M views",
        postedAt: "2 weeks ago"
    }
];

// Search suggestions data
const searchSuggestions = [
    "build a website",
    "javascript tutorial",
    "python for beginners",
    "music relaxation",
    "gaming highlights",
    "workout at home",
    "travel japan",
    "cooking italian food",
    "nature documentary",
    "ai chatbot python",
    "web development",
    "fitness motivation",
    "minecraft builds",
    "space exploration",
    "coding music"
];

// DOM Elements
const videoGrid = document.getElementById('videoGrid');
const menuBtn = document.getElementById('menuBtn');
const sidebar = document.getElementById('sidebar');
const mainContent = document.getElementById('mainContent');
const themeBtn = document.getElementById('themeBtn');
const searchInput = document.getElementById('searchInput');
const searchSuggestionsEl = document.getElementById('searchSuggestions');
const filterChips = document.querySelectorAll('.filter-chip');
const videoModal = document.getElementById('videoModal');
const closeModal = document.getElementById('closeModal');
const modalOverlay = document.getElementById('modalOverlay');
const modalVideoInfo = document.getElementById('modalVideoInfo');
const playerPlaceholder = document.getElementById('playerPlaceholder');

// State
let isDarkMode = false;
let isSidebarCollapsed = false;
let currentVideo = null;
let isPlaying = false;
let likedVideos = new Set();
let subscribedChannels = new Set();

// Initialize videos
function renderVideos(videoList) {
    videoGrid.innerHTML = '';
    
    videoList.forEach((video, index) => {
        const isLiked = likedVideos.has(video.id);
        
        const videoCard = document.createElement('button');
        videoCard.className = 'video-card';
        videoCard.dataset.id = video.id;
        videoCard.innerHTML = `
            <div class="thumbnail-container">
                <img src="${video.thumbnail}" alt="${video.title}" loading="lazy">
                <span class="duration">${video.duration}</span>
            </div>
            <div class="video-info">
                <div class="channel-avatar">
                    <img src="${video.channelAvatar}" alt="${video.channelName}">
                </div>
                <div class="video-details">
                    <h3 class="video-title">${video.title}</h3>
                    <p class="channel-name">${video.channelName}</p>
                    <p class="video-meta">${video.views} • ${video.postedAt}</p>
                    <div class="video-actions">
                        <button class="action-btn like-btn ${isLiked ? 'liked' : ''}" data-id="${video.id}">
                            <i class="fas fa-thumbs-up"></i>
                            <span>${isLiked ? 'Liked' : 'Like'}</span>
                        </button>
                        <button class="action-btn share-btn" data-id="${video.id}">
                            <i class="fas fa-share"></i>
                            <span>Share</span>
                        </button>
                        <button class="action-btn subscribe" data-channel="${video.channelName}">
                            <i class="fas fa-bell"></i>
                            <span>Subscribe</span>
                        </button>
                    </div>
                </div>
            </div>
        `;
        
        // Add click handler for video
        videoCard.addEventListener('click', (e) => {
            if (!e.target.closest('.action-btn')) {
                openVideoModal(video);
            }
        });
        
        videoGrid.appendChild(videoCard);
    });
    
    // Add event listeners for action buttons
    addActionListeners();
}

// Add event listeners for video actions
function addActionListeners() {
    document.querySelectorAll('.like-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const videoId = parseInt(btn.dataset.id);
            toggleLike(videoId, btn);
        });
    });
    
    document.querySelectorAll('.share-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const videoId = btn.dataset.id;
            shareVideo(videoId);
        });
    });
    
    document.querySelectorAll('.action-btn.subscribe').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const channelName = btn.dataset.channel;
            toggleSubscribe(channelName, btn);
        });
    });
}

// Toggle like
function toggleLike(videoId, btn) {
    if (likedVideos.has(videoId)) {
        likedVideos.delete(videoId);
        btn.classList.remove('liked');
        btn.querySelector('span').textContent = 'Like';
    } else {
        likedVideos.add(videoId);
        btn.classList.add('liked');
        btn.querySelector('span').textContent = 'Liked';
    }
    localStorage.setItem('likedVideos', JSON.stringify([...likedVideos]));
}

// Share video
function shareVideo(videoId) {
    const video = videos.find(v => v.id === parseInt(videoId));
    if (navigator.share) {
        navigator.share({
            title: video.title,
            text: `Check out this video: ${video.title}`,
            url: window.location.href
        });
    } else {
        // Fallback: copy to clipboard
        navigator.clipboard.writeText(window.location.href);
        alert('Link copied to clipboard!');
    }
}

// Toggle subscribe
function toggleSubscribe(channelName, btn) {
    if (subscribedChannels.has(channelName)) {
        subscribedChannels.delete(channelName);
        btn.classList.remove('subscribed');
        btn.querySelector('span').textContent = 'Subscribe';
    } else {
        subscribedChannels.add(channelName);
        btn.classList.add('subscribed');
        btn.querySelector('span').textContent = 'Subscribed';
    }
    localStorage.setItem('subscribedChannels', JSON.stringify([...subscribedChannels]));
}

// Open video modal
function openVideoModal(video) {
    currentVideo = video;
    isPlaying = false;
    
    document.querySelector('.modal-video-title').textContent = video.title;
    modalVideoInfo.innerHTML = `
        <h2 class="modal-video-title">${video.title}</h2>
        <div class="modal-video-stats">
            <span class="modal-views">${video.views} • ${video.postedAt}</span>
            <div class="modal-buttons">
                <button class="modal-btn like-btn ${likedVideos.has(video.id) ? 'active' : ''}" id="modalLike">
                    <i class="fas fa-thumbs-up"></i>
                    <span>${likedVideos.has(video.id) ? 'Liked' : 'Like'}</span>
                </button>
                <button class="modal-btn" id="modalDislike">
                    <i class="fas fa-thumbs-down"></i>
                    <span>Dislike</span>
                </button>
                <button class="modal-btn" id="modalShare">
                    <i class="fas fa-share"></i>
                    <span>Share</span>
                </button>
                <button class="modal-btn" id="modalSave">
                    <i class="fas fa-bookmark"></i>
                    <span>Save</span>
                </button>
            </div>
        </div>
        <div class="modal-channel-info">
            <div class="modal-channel-avatar">
                <img src="${video.channelAvatar}" alt="${video.channelName}">
            </div>
            <div class="modal-channel-details">
                <div class="modal-channel-name">${video.channelName}</div>
                <div class="modal-channel-subs">1.2M subscribers</div>
            </div>
            <button class="modal-subscribe-btn ${subscribedChannels.has(video.channelName) ? 'subscribed' : ''}" id="modalSubscribe">
                ${subscribedChannels.has(video.channelName) ? 'Subscribed' : 'Subscribe'}
            </button>
        </div>
    `;
    
    // Add modal button listeners
    document.getElementById('modalLike').addEventListener('click', () => {
        const btn = document.getElementById('modalLike');
        toggleLike(video.id, btn);
        btn.classList.toggle('active');
        btn.querySelector('span').textContent = btn.classList.contains('active') ? 'Liked' : 'Like';
    });
    
    document.getElementById('modalDislike').addEventListener('click', () => {
        const btn = document.getElementById('modalDislike');
        btn.classList.toggle('active');
    });
    
    document.getElementById('modalShare').addEventListener('click', () => shareVideo(video.id));
    
    document.getElementById('modalSave').addEventListener('click', () => {
        const btn = document.getElementById('modalSave');
        btn.classList.toggle('active');
    });
    
    document.getElementById('modalSubscribe').addEventListener('click', () => {
        const btn = document.getElementById('modalSubscribe');
        toggleSubscribe(video.channelName, btn);
        btn.classList.toggle('subscribed');
        btn.textContent = btn.classList.contains('subscribed') ? 'Subscribed' : 'Subscribe';
    });
    
    // Reset player
    playerPlaceholder.innerHTML = `
        <i class="fas fa-play-circle"></i>
        <p>Click to play video</p>
    `;
    isPlaying = false;
    
    videoModal.classList.add('active');
    document.body.style.overflow = 'hidden';
    
    // Add click handler for play
    playerPlaceholder.addEventListener('click', togglePlay);
}

// Toggle play/pause
function togglePlay() {
    isPlaying = !isPlaying;
    if (isPlaying) {
        playerPlaceholder.innerHTML = `
            <i class="fas fa-pause-circle"></i>
            <p>Playing...</p>
        `;
    } else {
        playerPlaceholder.innerHTML = `
            <i class="fas fa-play-circle"></i>
            <p>Click to play video</p>
        `;
    }
}

// Close modal
function closeVideoModal() {
    videoModal.classList.remove('active');
    document.body.style.overflow = '';
    currentVideo = null;
    isPlaying = false;
}

// Toggle sidebar
menuBtn.addEventListener('click', () => {
    if (window.innerWidth <= 900) {
        sidebar.classList.toggle('visible');
    } else {
        isSidebarCollapsed = !isSidebarCollapsed;
        if (isSidebarCollapsed) {
            sidebar.classList.add('mini');
            mainContent.classList.add('mini-sidebar');
        } else {
            sidebar.classList.remove('mini');
            mainContent.classList.remove('mini-sidebar');
        }
        localStorage.setItem('sidebarCollapsed', isSidebarCollapsed);
    }
});

// Theme toggle
themeBtn.addEventListener('click', () => {
    isDarkMode = !isDarkMode;
    document.documentElement.setAttribute('data-theme', isDarkMode ? 'dark' : 'light');
    
    const icon = themeBtn.querySelector('i');
    icon.className = isDarkMode ? 'fas fa-sun' : 'fas fa-moon';
    
    localStorage.setItem('theme', isDarkMode ? 'dark' : 'light');
});

// Load saved theme
function loadTheme() {
    const savedTheme = localStorage.getItem('theme');
    if (savedTheme === 'dark') {
        isDarkMode = true;
        document.documentElement.setAttribute('data-theme', 'dark');
        const icon = themeBtn.querySelector('i');
        icon.className = 'fas fa-sun';
    }
}

// Load saved sidebar state
function loadSidebarState() {
    const collapsed = localStorage.getItem('sidebarCollapsed') === 'true';
    if (collapsed && window.innerWidth > 900) {
        isSidebarCollapsed = true;
        sidebar.classList.add('mini');
        mainContent.classList.add('mini-sidebar');
    }
}

// Load saved data
function loadSavedData() {
    const liked = localStorage.getItem('likedVideos');
    if (liked) {
        likedVideos = new Set(JSON.parse(liked));
    }
    
    const subscribed = localStorage.getItem('subscribedChannels');
    if (subscribed) {
        subscribedChannels = new Set(JSON.parse(subscribed));
    }
}

// Filter chips
filterChips.forEach(chip => {
    chip.addEventListener('click', () => {
        filterChips.forEach(c => c.classList.remove('active'));
        chip.classList.add('active');
        
        const category = chip.textContent;
        if (category === 'All') {
            renderVideos(videos);
        } else {
            const filtered = [...videos].sort(() => Math.random() - 0.5);
            renderVideos(filtered);
        }
    });
});

// Search functionality
const searchBtn = document.querySelector('.search-btn');
searchBtn.addEventListener('click', performSearch);
searchInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') {
        performSearch();
    }
});

function performSearch() {
    const query = searchInput.value.toLowerCase().trim();
    hideSuggestions();
    
    if (!query) {
        renderVideos(videos);
        return;
    }
    
    const filtered = videos.filter(video => 
        video.title.toLowerCase().includes(query) ||
        video.channelName.toLowerCase().includes(query)
    );
    
    renderVideos(filtered);
}

// Search suggestions
searchInput.addEventListener('input', (e) => {
    const query = e.target.value.toLowerCase().trim();
    if (query.length > 0) {
        showSuggestions(query);
    } else {
        hideSuggestions();
    }
});

searchInput.addEventListener('focus', () => {
    const query = searchInput.value.toLowerCase().trim();
    if (query.length > 0) {
        showSuggestions(query);
    }
});

document.addEventListener('click', (e) => {
    if (!e.target.closest('.header-center')) {
        hideSuggestions();
    }
});

function showSuggestions(query) {
    const filtered = searchSuggestions.filter(s => s.includes(query));
    
    if (filtered.length === 0) {
        hideSuggestions();
        return;
    }
    
    searchSuggestionsEl.innerHTML = filtered.map(s => `
        <div class="suggestion-item" data-query="${s}">
            <i class="fas fa-search"></i>
            <span>${s}</span>
        </div>
    `).join('');
    
    searchSuggestionsEl.classList.add('active');
    
    // Add click handlers
    document.querySelectorAll('.suggestion-item').forEach(item => {
        item.addEventListener('click', () => {
            searchInput.value = item.dataset.query;
            performSearch();
        });
    });
}

function hideSuggestions() {
    searchSuggestionsEl.classList.remove('active');
}

// Mic button
const micBtn = document.querySelector('.mic-btn');
micBtn.addEventListener('click', () => {
    micBtn.classList.toggle('listening');
    if (micBtn.classList.contains('listening')) {
        // Simulate voice recognition
        setTimeout(() => {
            micBtn.classList.remove('listening');
        }, 3000);
    }
});

// Modal events
closeModal.addEventListener('click', closeVideoModal);
modalOverlay.addEventListener('click', closeVideoModal);

document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && videoModal.classList.contains('active')) {
        closeVideoModal();
    }
});

// Keyboard navigation
let focusedIndex = -1;

videoGrid.addEventListener('keydown', (e) => {
    const cards = document.querySelectorAll('.video-card');
    const totalCards = cards.length;
    
    if (e.key === 'ArrowRight') {
        e.preventDefault();
        focusedIndex = Math.min(focusedIndex + 1, totalCards - 1);
        cards[focusedIndex]?.focus();
    } else if (e.key === 'ArrowLeft') {
        e.preventDefault();
        focusedIndex = Math.max(focusedIndex - 1, 0);
        cards[focusedIndex]?.focus();
    } else if (e.key === 'ArrowDown') {
        e.preventDefault();
        const columns = Math.floor(videoGrid.offsetWidth / 340) || 1;
        focusedIndex = Math.min(focusedIndex + columns, totalCards - 1);
        cards[focusedIndex]?.focus();
    } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        const columns = Math.floor(videoGrid.offsetWidth / 340) || 1;
        focusedIndex = Math.max(focusedIndex - columns, 0);
        cards[focusedIndex]?.focus();
    } else if (e.key === 'Enter' && focusedIndex >= 0) {
        const videoId = parseInt(cards[focusedIndex].dataset.id);
        const video = videos.find(v => v.id === videoId);
        openVideoModal(video);
    }
});

// Handle window resize
window.addEventListener('resize', () => {
    if (window.innerWidth > 900) {
        sidebar.classList.remove('visible');
    }
});

// Initialize
loadTheme();
loadSidebarState();
loadSavedData();
renderVideos(videos);
