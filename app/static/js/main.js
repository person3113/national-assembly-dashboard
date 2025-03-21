// 문서 준비 완료 이벤트
document.addEventListener('DOMContentLoaded', function() {
    console.log('국회정보 대시보드가 로드되었습니다.');

    // 경고창 자동 닫기
    const alerts = document.querySelectorAll('.alert-dismissible');
    alerts.forEach(alert => {
        setTimeout(() => {
            const closeBtn = alert.querySelector('.btn-close');
            if (closeBtn) {
                closeBtn.click();
            }
        }, 5000);
    });

    // 테이블 행 클릭 시 상세 페이지로 이동
    const clickableTables = document.querySelectorAll('.table-clickable');
    clickableTables.forEach(table => {
        const rows = table.querySelectorAll('tbody tr');
        rows.forEach(row => {
            row.style.cursor = 'pointer';
            row.addEventListener('click', function() {
                const link = this.getAttribute('data-href');
                if (link) {
                    window.location.href = link;
                }
            });
        });
    });

    // 툴팁 초기화 (Bootstrap 5)
    const tooltips = document.querySelectorAll('[data-bs-toggle="tooltip"]');
    if (tooltips.length > 0 && typeof bootstrap !== 'undefined') {
        tooltips.forEach(tooltip => {
            new bootstrap.Tooltip(tooltip);
        });
    }
});

// 날짜 형식 변환 함수
function formatDate(dateString) {
    if (!dateString) return '';
    
    const date = new Date(dateString);
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    
    return `${year}-${month}-${day}`;
}

// 숫자 형식 변환 함수
function formatNumber(number) {
    return number.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ",");
}
