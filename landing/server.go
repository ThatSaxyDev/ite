package main

import (
	"embed"
	"fmt"
	"html/template"
	"log"
	"net/http"
	"os"
	"strings"
	"time"

	"github.com/gorilla/mux"
)

//go:embed index.html
var landingFS embed.FS

// Template data for dynamic content
type PageData struct {
	Title       string
	Description string
	Version     string
	Year        int
}

// ResponseWriter wrapper for logging
type statusRecorder struct {
	http.ResponseWriter
	status int
}

func (r *statusRecorder) WriteHeader(status int) {
	r.status = status
	r.ResponseWriter.WriteHeader(status)
}

func loggingMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		start := time.Now()
		rec := &statusRecorder{w, http.StatusOK}
		next.ServeHTTP(rec, r)
		
		// Skip favicon
		if r.URL.Path == "/favicon.ico" {
			return
		}
		
		fmt.Printf("[%s] %s %s %dms\n", 
			time.Now().Format("15:04:05"),
			r.Method,
			r.URL.Path,
			time.Since(start).Milliseconds(),
		)
	})
}

func cacheMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// Add cache headers for static assets
		if strings.HasSuffix(r.URL.Path, ".css") || 
		   strings.HasSuffix(r.URL.Path, ".js") ||
		   strings.HasSuffix(r.URL.Path, ".svg") ||
		   strings.HasSuffix(r.URL.Path, ".png") ||
		   strings.HasSuffix(r.URL.Path, ".jpg") {
			w.Header().Set("Cache-Control", "public, max-age=31536000, immutable")
		} else {
			w.Header().Set("Cache-Control", "no-cache, no-store, must-revalidate")
		}
		w.Header().Set("X-Content-Type-Options", "nosniff")
		w.Header().Set("X-Frame-Options", "DENY")
		w.Header().Set("X-XSS-Protection", "1; mode=block")
		next.ServeHTTP(w, r)
	})
}

func securityHeaders(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
		w.Header().Set("Referrer-Policy", "strict-origin-when-cross-origin")
		next.ServeHTTP(w, r)
	})
}

func landingHandler(w http.ResponseWriter, r *http.Request) {
	data := PageData{
		Title:       "ITE — Interactive Terminal Environment",
		Description: "A powerful AI coding agent that lives in your terminal. Code smarter, ship faster, stay in flow.",
		Version:     "v1.0.0",
		Year:        time.Now().Year(),
	}

	// Parse and serve the embedded template
	tmpl, err := template.ParseFS(landingFS, "index.html")
	if err != nil {
		log.Printf("Template error: %v", err)
		http.Error(w, "Internal Server Error", http.StatusInternalServerError)
		return
	}

	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	if err := tmpl.Execute(w, data); err != nil {
		log.Printf("Template execution error: %v", err)
	}
}

func healthHandler(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	fmt.Fprint(w, `{"status":"healthy","service":"ite-landing"}`)
}

func main() {
	port := getEnv("PORT", "8080")
	
	router := mux.NewRouter()
	
	// API routes
	router.HandleFunc("/health", healthHandler).Methods("GET")
	router.HandleFunc("/api/status", healthHandler).Methods("GET")
	
	// Main landing page
	router.HandleFunc("/", landingHandler).Methods("GET")
	
	// Apply middleware
	stack := securityHeaders(cacheMiddleware(loggingMiddleware(router)))
	
	addr := fmt.Sprintf(":%s", port)
	fmt.Printf(`
╔═══════════════════════════════════════════════════════════════╗
║                                                               ║
║   ██╗   ██╗███╗   ███╗██╗███████╗███████╗██╗                  ║
║   ██║   ██║████╗ ████║██║██╔════╝██╔════╝██║                  ║
║   ██║   ██║██╔████╔██║██║███████╗███████╗██║                  ║
║   ██║   ██║██║╚██╔╝██║██║╚════██║╚════██║██║                  ║
║   ╚██████╔╝██║ ╚═╝ ██║██║███████║███████║███████╗             ║
║    ╚═════╝ ╚═╝     ╚═╝╚═╝╚══════╝╚══════╝╚══════╝             ║
║                    Terminal Environment                        ║
║                                                               ║
║   🌐 Server:  http://localhost:%s                           ║
║   📖 Health:  http://localhost:%s/health                      ║
║                                                               ║
╚═══════════════════════════════════════════════════════════════╝
`, port, port)
	
	log.Printf("Starting ITE landing server on :%s", port)
	if err := http.ListenAndServe(addr, stack); err != nil {
		log.Fatalf("Server failed: %v", err)
	}
}

func getEnv(key, defaultValue string) string {
	if value := strings.TrimSpace(os.Getenv(key)); value != "" {
		return value
	}
	return defaultValue
}
